import hashlib
import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidates import AdvertisementSplitStatus
from app.models.confidence import (
    ConfidencePolicyVersion,
    FieldConfidenceAssessment,
    FieldCriticality,
    ReviewPriority,
    RevisionConfidenceAssessment,
)
from app.models.source_registry import SourceClass
from app.models.verification import (
    EvidenceAssessmentType,
    FieldVerification,
    FieldVerificationOutcome,
    FieldVerificationStatus,
    VerificationRunStatus,
)
from app.repositories.candidates import CandidateRevisionRepository
from app.repositories.confidence import FieldConfidenceRepository, RevisionConfidenceRepository
from app.repositories.verification import FieldVerificationRepository, VerificationRunRepository
from app.services.confidence_policy import ConfidencePolicyV2, classify_field_criticality_v2
from app.services.exceptions import DomainConflictError, ResourceNotFoundError


class ConfidenceV2Service:
    """Calculate reliability only; all V2 review columns remain deliberately neutral."""

    def __init__(self, session: Session, *, commit: bool = True) -> None:
        self.session = session
        self.commit = commit
        self.policy = ConfidencePolicyV2()
        self.fields = FieldVerificationRepository(session)
        self.runs = VerificationRunRepository(session)
        self.revisions = CandidateRevisionRepository(session)
        self.field_confidence = FieldConfidenceRepository(session)
        self.revision_confidence = RevisionConfidenceRepository(session)

    def score_run(
        self, verification_run_id: uuid.UUID
    ) -> tuple[RevisionConfidenceAssessment, list[FieldConfidenceAssessment], bool]:
        run = self.runs.get(verification_run_id)
        if run is None:
            raise ResourceNotFoundError("Verification run not found")
        if run.status not in {VerificationRunStatus.COMPLETED, VerificationRunStatus.PARTIAL}:
            raise DomainConflictError("Confidence requires a COMPLETED or PARTIAL verification run")
        verifications = self.fields.list_for_run(run.id)
        field_assessments = [
            self._get_or_build_field(item)[0]
            for item in verifications
            if item.status == FieldVerificationStatus.FINALIZED
        ]
        self.session.flush()
        data = self._revision_result(run, field_assessments)
        existing = self.revision_confidence.get_for_policy(run.id, ConfidencePolicyVersion.V2)
        if existing is not None:
            self._assert_matches(existing, data, {"verification_run_id", "candidate_revision_id"})
            if self.commit:
                self.session.rollback()
            return existing, self._list_fields(run.id), False
        assessment = RevisionConfidenceAssessment(**data)
        self.revision_confidence.add(assessment)
        try:
            self._save()
        except IntegrityError as error:
            if self.commit:
                self.session.rollback()
            existing = self.revision_confidence.get_for_policy(run.id, ConfidencePolicyVersion.V2)
            if existing is not None:
                self._assert_matches(
                    existing, data, {"verification_run_id", "candidate_revision_id"}
                )
                return existing, self._list_fields(run.id), False
            raise DomainConflictError("Concurrent Confidence V2 calculation conflicted") from error
        return assessment, self._list_fields(run.id), True

    def get_revision_assessment(
        self, verification_run_id: uuid.UUID
    ) -> tuple[RevisionConfidenceAssessment, list[FieldConfidenceAssessment]]:
        if self.runs.get(verification_run_id) is None:
            raise ResourceNotFoundError("Verification run not found")
        assessment = self.revision_confidence.get_for_policy(
            verification_run_id, ConfidencePolicyVersion.V2
        )
        if assessment is None:
            raise ResourceNotFoundError("Confidence V2 assessment not found")
        return assessment, self._list_fields(verification_run_id)

    def _get_or_build_field(
        self, verification: FieldVerification
    ) -> tuple[FieldConfidenceAssessment, bool]:
        data = self._field_result(verification)
        existing = self.field_confidence.get_for_policy(verification.id, ConfidencePolicyVersion.V2)
        if existing is not None:
            self._assert_matches(existing, data, {"field_verification_id"})
            return existing, False
        assessment = FieldConfidenceAssessment(**data)
        self.field_confidence.add(assessment)
        return assessment, True

    def _field_result(self, verification: FieldVerification) -> dict[str, Any]:
        if verification.status != FieldVerificationStatus.FINALIZED:
            raise DomainConflictError("Only finalized field verifications can be scored")
        revision = self.revisions.get(verification.verification_run.candidate_revision_id)
        if revision is None:
            raise DomainConflictError("Candidate revision is unavailable")
        field = next(
            (item for item in revision.fields if item.id == verification.candidate_field_id), None
        )
        if field is None:
            raise DomainConflictError("Candidate field is unavailable")
        counts = self._assessment_counts(verification)
        base = {
            FieldVerificationOutcome.CONFIRMED: self.policy.confirmed_base,
            FieldVerificationOutcome.CONFLICT: self.policy.conflict_base,
            FieldVerificationOutcome.INSUFFICIENT_EVIDENCE: self.policy.insufficient_base,
            FieldVerificationOutcome.NOT_APPLICABLE: None,
        }[verification.outcome]
        authoritative_points = self.policy.authoritative_support if counts["auth_support"] else 0
        official_points = self.policy.official_support if counts["official_support"] else 0
        secondary_points = self.policy.secondary_support if counts["secondary_support"] else 0
        extraction_tier, extraction_points = self._extraction_reliability(
            revision.extraction_method
        )
        locator_points = self.policy.located_value if field.source_locator else 0
        supporting_points = min(
            max(counts["support_total"] - 1, 0), self.policy.supporting_evidence_cap
        )
        conflict_points = (
            self.policy.authoritative_conflict * int(bool(counts["auth_conflict"]))
            + self.policy.official_conflict * int(bool(counts["official_conflict"]))
            + self.policy.secondary_conflict * int(bool(counts["secondary_conflict"]))
        )
        ambiguous = field.field_path == "extraction.ambiguities"
        ambiguity_points = self.policy.ambiguity if ambiguous else 0
        components = {
            "verification_outcome": base,
            "authoritative_source_quality": authoritative_points,
            "official_source_quality": official_points,
            "secondary_source_quality": secondary_points,
            "extraction_reliability": extraction_points,
            "source_locator_completeness": locator_points,
            "supporting_evidence": supporting_points,
            "conflicts": conflict_points,
            "ambiguity": ambiguity_points,
        }
        score = None if base is None else max(0, min(100, sum(components.values())))
        criticality = classify_field_criticality_v2(field.field_path)
        fingerprint = self._hash(
            {
                "policy": self.policy.as_dict(),
                "verification_id": str(verification.id),
                "field_id": str(field.id),
                "field_path": field.field_path,
                "field_value": verification.candidate_field_value_snapshot,
                "field_type": verification.candidate_field_type_snapshot.value,
                "outcome": verification.outcome.value,
                "reason": verification.reason_code.value,
                "extraction_method": revision.extraction_method,
                "source_locator": field.source_locator,
                "assessments": self._assessment_facts(verification),
            }
        )
        return {
            "field_verification_id": verification.id,
            "policy_version": ConfidencePolicyVersion.V2,
            "input_hash": fingerprint,
            "score": score,
            "criticality": criticality,
            "review_required": False,
            "review_priority": ReviewPriority.NONE,
            "review_reason_codes": [],
            "component_breakdown": {
                "policy": self.policy.as_dict(),
                "components": components,
                "evidence_counts": counts,
                "extraction_method": revision.extraction_method,
                "extraction_reliability_tier": extraction_tier,
                "final_score": score,
            },
        }

    def _revision_result(self, run, fields: list[FieldConfidenceAssessment]) -> dict[str, Any]:
        revision = self.revisions.get(run.candidate_revision_id)
        if revision is None or revision.revision_hash != run.candidate_revision_hash_snapshot:
            raise DomainConflictError("Verification run revision snapshot mismatch")
        finalized = len(fields)
        coverage = (Decimal(finalized) / Decimal(run.fields_total)).quantize(Decimal("0.0001"))
        scored = [item for item in fields if item.score is not None]
        weights = [2 if item.criticality == FieldCriticality.CRITICAL else 1 for item in scored]
        weighted_sum = sum(
            Decimal(item.score) * weight for item, weight in zip(scored, weights, strict=True)
        )
        score = (
            int(
                (weighted_sum / Decimal(sum(weights))).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            if weights
            else None
        )
        split_status = (
            revision.advertisement_revision.split_status
            if revision.advertisement_revision is not None
            else AdvertisementSplitStatus.LEGACY_UNSPLIT
        )
        split_penalty = 20 if split_status == AdvertisementSplitStatus.AMBIGUOUS else 0
        if score is not None:
            score = max(0, score - split_penalty)
        post_count = (
            len(revision.advertisement_revision.posts)
            if revision.advertisement_revision is not None
            else 0
        )
        critical_total = sum(item.criticality == FieldCriticality.CRITICAL for item in fields)
        rows = [
            {
                "field_confidence_assessment_id": str(item.id),
                "field_verification_id": str(item.field_verification_id),
                "criticality": item.criticality.value,
                "score": item.score,
            }
            for item in sorted(fields, key=lambda value: str(value.field_verification_id))
        ]
        breakdown = {
            "policy": self.policy.as_dict(),
            "aggregation": {
                "method": "criticality_weighted_average_of_present_verified_facts",
                "optional_absence_penalty": 0,
                "coverage": str(coverage),
                "weighted_sum": str(weighted_sum),
                "total_weight": sum(weights),
            },
            "advertisement": {
                "split_status": split_status.value,
                "post_count": post_count,
                "ambiguous_split_penalty": split_penalty,
            },
            "fields": rows,
            "final_score": score,
        }
        fingerprint = self._hash(
            {
                "policy": self.policy.as_dict(),
                "run_id": str(run.id),
                "revision_id": str(revision.id),
                "revision_hash": revision.revision_hash,
                "run_status": run.status.value,
                "field_inputs": [
                    {"id": str(item.id), "input_hash": item.input_hash}
                    for item in sorted(fields, key=lambda value: str(value.id))
                ],
                "split_status": split_status.value,
                "post_count": post_count,
            }
        )
        return {
            "verification_run_id": run.id,
            "candidate_revision_id": revision.id,
            "policy_version": ConfidencePolicyVersion.V2,
            "input_hash": fingerprint,
            "score": score,
            "coverage_ratio": coverage,
            "fields_total": run.fields_total,
            "fields_scored": len(scored),
            "fields_not_applicable": finalized - len(scored),
            "critical_fields_total": critical_total,
            "critical_fields_requiring_review": 0,
            "fields_requiring_review": 0,
            "review_required": False,
            "review_priority": ReviewPriority.NONE,
            "review_reason_codes": [],
            "component_breakdown": breakdown,
        }

    @staticmethod
    def _assessment_counts(verification: FieldVerification) -> dict[str, int]:
        result = {
            "auth_support": 0,
            "official_support": 0,
            "secondary_support": 0,
            "auth_conflict": 0,
            "official_conflict": 0,
            "secondary_conflict": 0,
        }
        source_names = {
            SourceClass.AUTHORITATIVE_OFFICIAL: "auth",
            SourceClass.OFFICIAL_SUPPORTING: "official",
            SourceClass.SECONDARY_DISCOVERY_ONLY: "secondary",
        }
        seen: set[tuple[str, str, str]] = set()
        for item in verification.assessments:
            if item.assessment == EvidenceAssessmentType.CONTEXT_ONLY:
                continue
            direction = (
                "support" if item.assessment == EvidenceAssessmentType.SUPPORTS else "conflict"
            )
            source = source_names[item.source_class_snapshot]
            endpoint_id = str(item.evidence.source_document.source_endpoint_id)
            seen.add((source, direction, endpoint_id))
        for source, direction, _ in seen:
            result[f"{source}_{direction}"] += 1
        result["support_total"] = sum(
            value for key, value in result.items() if key.endswith("support")
        )
        return result

    @staticmethod
    def _assessment_facts(verification: FieldVerification) -> list[dict[str, str]]:
        return sorted(
            [
                {
                    "evidence_id": str(item.evidence_id),
                    "evidence_hash": item.evidence.evidence_hash,
                    "source_document_hash": item.evidence.source_document.content_hash,
                    "source_endpoint_id": str(item.evidence.source_document.source_endpoint_id),
                    "source_class": item.source_class_snapshot.value,
                    "assessment": item.assessment.value,
                }
                for item in verification.assessments
            ],
            key=lambda item: (item["evidence_id"], item["assessment"]),
        )

    def _extraction_reliability(self, method: str | None) -> tuple[str, int]:
        normalized = (method or "").upper()
        if normalized == "CONTROLLED_INPUT" or normalized.endswith("_V1"):
            return "DETERMINISTIC", self.policy.reliable_extraction
        if normalized:
            return "DECLARED_UNKNOWN", self.policy.declared_extraction
        return "UNRECORDED", 0

    def _list_fields(self, run_id: uuid.UUID) -> list[FieldConfidenceAssessment]:
        return self.field_confidence.list_for_run(run_id, ConfidencePolicyVersion.V2)

    def _save(self) -> None:
        self.session.commit() if self.commit else self.session.flush()

    @staticmethod
    def _assert_matches(existing, data: dict[str, Any], ignored: set[str]) -> None:
        if any(
            getattr(existing, key) != value for key, value in data.items() if key not in ignored
        ):
            raise DomainConflictError(
                "Persisted Confidence V2 output or inputs fail integrity validation"
            )

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
