import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidates import AdvertisementSplitStatus
from app.models.confidence import ConfidencePolicyVersion, FieldCriticality, ReviewPriority
from app.models.review_routing import (
    ReviewRoutingAssessment,
    ReviewRoutingPolicyVersion,
    ReviewRoutingReasonCode,
)
from app.models.verification import (
    FieldVerificationOutcome,
    VerificationReasonCode,
    VerificationRunStatus,
)
from app.repositories.candidates import CandidateRevisionRepository
from app.repositories.confidence import RevisionConfidenceRepository
from app.repositories.review_routing import ReviewRoutingRepository
from app.repositories.verification import FieldVerificationRepository, VerificationRunRepository
from app.services.confidence_v2 import ConfidenceV2Service
from app.services.exceptions import DomainConflictError, ResourceNotFoundError

PRIORITY_RANK = {
    ReviewPriority.NONE: 0,
    ReviewPriority.NORMAL: 1,
    ReviewPriority.HIGH: 2,
    ReviewPriority.CRITICAL: 3,
}


class ReviewRoutingService:
    """Route semantic risk independently of numeric reliability or publication."""

    def __init__(self, session: Session, *, commit: bool = True) -> None:
        self.session = session
        self.commit = commit
        self.confidence = RevisionConfidenceRepository(session)
        self.routing = ReviewRoutingRepository(session)
        self.runs = VerificationRunRepository(session)
        self.fields = FieldVerificationRepository(session)
        self.revisions = CandidateRevisionRepository(session)

    def assess(
        self, revision_confidence_assessment_id: uuid.UUID
    ) -> tuple[ReviewRoutingAssessment, bool]:
        confidence = self.confidence.get(revision_confidence_assessment_id)
        if confidence is None:
            raise ResourceNotFoundError("Revision confidence assessment not found")
        if confidence.policy_version != ConfidencePolicyVersion.V2:
            raise DomainConflictError("Review Routing V1 requires Confidence V2")
        validated, field_confidences, _ = ConfidenceV2Service(self.session, commit=False).score_run(
            confidence.verification_run_id
        )
        if validated.id != confidence.id:
            raise DomainConflictError("Confidence V2 identity mismatch")
        data = self._result(confidence, field_confidences)
        existing = self.routing.get_for_policy(confidence.id, ReviewRoutingPolicyVersion.V1)
        if existing is not None:
            self._assert_matches(existing, data)
            if self.commit:
                self.session.rollback()
            return existing, False
        assessment = ReviewRoutingAssessment(**data)
        self.routing.add(assessment)
        try:
            self.session.commit() if self.commit else self.session.flush()
        except IntegrityError as error:
            if self.commit:
                self.session.rollback()
            existing = self.routing.get_for_policy(confidence.id, ReviewRoutingPolicyVersion.V1)
            if existing is not None:
                self._assert_matches(existing, data)
                return existing, False
            raise DomainConflictError("Concurrent review-routing assessment conflicted") from error
        return assessment, True

    def get(self, revision_confidence_assessment_id: uuid.UUID) -> ReviewRoutingAssessment:
        assessment = self.routing.get_for_policy(
            revision_confidence_assessment_id, ReviewRoutingPolicyVersion.V1
        )
        if assessment is None:
            raise ResourceNotFoundError("Review-routing assessment not found")
        return assessment

    def _result(self, confidence, field_confidences) -> dict[str, Any]:
        run = self.runs.get(confidence.verification_run_id)
        revision = self.revisions.get(confidence.candidate_revision_id)
        if run is None or revision is None:
            raise DomainConflictError("Routing inputs are unavailable")
        field_routes: list[dict[str, Any]] = []
        all_reasons: set[ReviewRoutingReasonCode] = set()
        overall_priority = ReviewPriority.NONE

        for field_confidence in field_confidences:
            verification = self.fields.get(field_confidence.field_verification_id)
            if verification is None:
                raise DomainConflictError("Routing field verification is unavailable")
            reasons: set[ReviewRoutingReasonCode] = set()
            if verification.reason_code == VerificationReasonCode.AUTHORITATIVE_CONFLICT:
                reasons.add(ReviewRoutingReasonCode.AUTHORITATIVE_CONFLICT)
            elif verification.outcome == FieldVerificationOutcome.CONFLICT:
                reasons.add(ReviewRoutingReasonCode.SOURCE_CONFLICT)
            if (
                field_confidence.criticality == FieldCriticality.CRITICAL
                and verification.outcome == FieldVerificationOutcome.INSUFFICIENT_EVIDENCE
            ):
                reasons.add(ReviewRoutingReasonCode.INSUFFICIENT_CRITICAL_EVIDENCE)
                reasons.add(ReviewRoutingReasonCode.UNCLEAR_CRITICAL_MEANING)
            if verification.candidate_field_path_snapshot == "extraction.ambiguities":
                reasons.add(ReviewRoutingReasonCode.AMBIGUOUS_POST_DETAILS)
                text = json.dumps(verification.candidate_field_value_snapshot).lower()
                if any(term in text for term in ("vacancy", "category", "total")):
                    reasons.add(ReviewRoutingReasonCode.UNCERTAIN_VACANCY_MAPPING)
                if any(term in text for term in ("matches multiple posts", "ownership", "attach")):
                    reasons.add(ReviewRoutingReasonCode.POSSIBLE_WRONG_POST_OWNERSHIP)
            if not reasons:
                continue
            priority = self._field_priority(field_confidence.criticality, reasons)
            overall_priority = max(overall_priority, priority, key=lambda item: PRIORITY_RANK[item])
            all_reasons.update(reasons)
            field_routes.append(
                {
                    "field_confidence_assessment_id": str(field_confidence.id),
                    "field_verification_id": str(verification.id),
                    "candidate_field_id": str(verification.candidate_field_id),
                    "field_path": verification.candidate_field_path_snapshot,
                    "criticality": field_confidence.criticality.value,
                    "priority": priority.value,
                    "reason_codes": self._ordered(reasons),
                }
            )

        split_status = (
            revision.advertisement_revision.split_status
            if revision.advertisement_revision is not None
            else AdvertisementSplitStatus.LEGACY_UNSPLIT
        )
        if split_status == AdvertisementSplitStatus.AMBIGUOUS:
            all_reasons.update(
                {
                    ReviewRoutingReasonCode.AMBIGUOUS_POST_SPLIT,
                    ReviewRoutingReasonCode.UNCERTAIN_VACANCY_MAPPING,
                }
            )
            overall_priority = max(
                overall_priority, ReviewPriority.HIGH, key=lambda item: PRIORITY_RANK[item]
            )
        if run.status == VerificationRunStatus.PARTIAL:
            all_reasons.add(ReviewRoutingReasonCode.PARTIAL_VERIFICATION)
            overall_priority = max(
                overall_priority, ReviewPriority.NORMAL, key=lambda item: PRIORITY_RANK[item]
            )
        field_routes.sort(key=lambda item: (item["field_path"], item["field_verification_id"]))
        reasons = self._ordered(all_reasons)
        breakdown = {
            "policy": {
                "policy_version": ReviewRoutingPolicyVersion.V1.value,
                "numeric_score_threshold_used": False,
                "optional_field_absence_routes": False,
                "publication_decision": False,
            },
            "advertisement_split_status": split_status.value,
            "field_route_count": len(field_routes),
            "confidence_policy": confidence.policy_version.value,
        }
        fingerprint = self._hash(
            {
                "policy": breakdown["policy"],
                "confidence_id": str(confidence.id),
                "confidence_input_hash": confidence.input_hash,
                "run_status": run.status.value,
                "split_status": split_status.value,
                "reasons": reasons,
                "field_routes": field_routes,
            }
        )
        return {
            "revision_confidence_assessment_id": confidence.id,
            "verification_run_id": run.id,
            "candidate_revision_id": revision.id,
            "policy_version": ReviewRoutingPolicyVersion.V1,
            "input_hash": fingerprint,
            "review_required": bool(reasons),
            "priority": overall_priority,
            "reason_codes": reasons,
            "field_routes": field_routes,
            "component_breakdown": breakdown,
        }

    @staticmethod
    def _field_priority(criticality, reasons) -> ReviewPriority:
        if (
            criticality == FieldCriticality.CRITICAL
            and ReviewRoutingReasonCode.AUTHORITATIVE_CONFLICT in reasons
        ):
            return ReviewPriority.CRITICAL
        if criticality == FieldCriticality.CRITICAL or any(
            reason
            in {
                ReviewRoutingReasonCode.AUTHORITATIVE_CONFLICT,
                ReviewRoutingReasonCode.UNCERTAIN_VACANCY_MAPPING,
                ReviewRoutingReasonCode.POSSIBLE_WRONG_POST_OWNERSHIP,
            }
            for reason in reasons
        ):
            return ReviewPriority.HIGH
        return ReviewPriority.NORMAL

    @staticmethod
    def _ordered(reasons) -> list[str]:
        selected = set(reasons)
        return [item.value for item in ReviewRoutingReasonCode if item in selected]

    @staticmethod
    def _assert_matches(existing, data: dict[str, Any]) -> None:
        if any(
            getattr(existing, key) != value
            for key, value in data.items()
            if key
            not in {
                "revision_confidence_assessment_id",
                "verification_run_id",
                "candidate_revision_id",
            }
        ):
            raise DomainConflictError(
                "Persisted review-routing output or inputs fail integrity validation"
            )

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
