import hashlib
import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.confidence import (
    ConfidencePolicyVersion,
    FieldConfidenceAssessment,
    FieldCriticality,
    ReviewPriority,
    ReviewReasonCode,
    RevisionConfidenceAssessment,
)
from app.models.source_registry import SourceClass
from app.models.verification import (
    EvidenceAssessmentType,
    FieldVerification,
    FieldVerificationOutcome,
    FieldVerificationStatus,
    VerificationReasonCode,
    VerificationRunStatus,
)
from app.repositories.candidates import CandidateRevisionRepository
from app.repositories.confidence import (
    FieldConfidenceRepository,
    RevisionConfidenceRepository,
)
from app.repositories.evidence import CandidateFieldEvidenceRepository
from app.repositories.verification import (
    FieldVerificationRepository,
    VerificationRunRepository,
)
from app.services.confidence_policy import (
    ConfidencePolicyV1,
    classify_field_criticality,
)
from app.services.exceptions import DomainConflictError, ResourceNotFoundError

PRIORITY_RANK = {
    ReviewPriority.NONE: 0,
    ReviewPriority.NORMAL: 1,
    ReviewPriority.HIGH: 2,
    ReviewPriority.CRITICAL: 3,
}


class ConfidenceService:
    def __init__(
        self,
        session: Session,
        policy: ConfidencePolicyV1 | None = None,
        *,
        commit: bool = True,
    ) -> None:
        self.session = session
        self.commit = commit
        self.policy = policy or ConfidencePolicyV1.from_settings(get_settings())
        self.fields = FieldVerificationRepository(session)
        self.runs = VerificationRunRepository(session)
        self.revisions = CandidateRevisionRepository(session)
        self.extraction_evidence = CandidateFieldEvidenceRepository(session)
        self.field_confidence = FieldConfidenceRepository(session)
        self.revision_confidence = RevisionConfidenceRepository(session)

    def score_field(
        self, field_verification_id: uuid.UUID
    ) -> tuple[FieldConfidenceAssessment, bool]:
        verification = self._get_finalized_field(field_verification_id)
        assessment, created = self._get_or_build_field_assessment(verification)
        if not created:
            return assessment, False
        try:
            self._save()
        except IntegrityError as error:
            self.session.rollback()
            existing = self.field_confidence.get_for_policy(
                verification.id, ConfidencePolicyVersion.V1
            )
            if existing is not None:
                self._assert_fingerprint(existing.input_hash, verification)
                return existing, False
            raise DomainConflictError(
                "Field confidence conflicted with concurrent calculation; retry"
            ) from error
        return assessment, True

    def get_field_assessment(self, field_verification_id: uuid.UUID) -> FieldConfidenceAssessment:
        if self.fields.get(field_verification_id) is None:
            raise ResourceNotFoundError("Field verification not found")
        assessment = self.field_confidence.get_for_policy(
            field_verification_id, ConfidencePolicyVersion.V1
        )
        if assessment is None:
            raise ResourceNotFoundError("Field confidence assessment not found")
        return assessment

    def score_run(
        self, verification_run_id: uuid.UUID
    ) -> tuple[RevisionConfidenceAssessment, list[FieldConfidenceAssessment], bool]:
        run = self._get_scorable_run(verification_run_id)
        verifications = self.fields.list_for_run(run.id)
        finalized = [
            item for item in verifications if item.status == FieldVerificationStatus.FINALIZED
        ]
        field_assessments: list[FieldConfidenceAssessment] = []
        for verification in finalized:
            assessment, _ = self._get_or_build_field_assessment(verification)
            field_assessments.append(assessment)
        self.session.flush()

        data = self._revision_result(run, field_assessments)
        existing = self.revision_confidence.get_for_policy(run.id, ConfidencePolicyVersion.V1)
        if existing is not None:
            if not self._revision_assessment_matches(existing, data):
                raise DomainConflictError(
                    "Persisted revision confidence output or inputs fail integrity validation"
                )
            if self.commit:
                self.session.rollback()
            return existing, self._list_field_assessments(run.id), False

        assessment = RevisionConfidenceAssessment(**data)
        self.revision_confidence.add(assessment)
        try:
            self._save()
        except IntegrityError as error:
            if self.commit:
                self.session.rollback()
            existing = self.revision_confidence.get_for_policy(run.id, ConfidencePolicyVersion.V1)
            if existing is not None and self._revision_assessment_matches(existing, data):
                return existing, self._list_field_assessments(run.id), False
            raise DomainConflictError(
                "Revision confidence conflicted with concurrent calculation; retry"
            ) from error
        return assessment, self._list_field_assessments(run.id), True

    def get_revision_assessment(
        self, verification_run_id: uuid.UUID
    ) -> tuple[RevisionConfidenceAssessment, list[FieldConfidenceAssessment]]:
        if self.runs.get(verification_run_id) is None:
            raise ResourceNotFoundError("Verification run not found")
        assessment = self.revision_confidence.get_for_policy(
            verification_run_id, ConfidencePolicyVersion.V1
        )
        if assessment is None:
            raise ResourceNotFoundError("Revision confidence assessment not found")
        return assessment, self._list_field_assessments(verification_run_id)

    @classmethod
    def validate_persisted_revision_assessment(
        cls,
        session: Session,
        assessment: RevisionConfidenceAssessment,
        *,
        commit: bool = True,
    ) -> list[FieldConfidenceAssessment]:
        if assessment.policy_version != ConfidencePolicyVersion.V1:
            raise DomainConflictError("Unsupported confidence policy version")
        policy_data = assessment.component_breakdown.get("policy", {})
        try:
            policy = ConfidencePolicyV1(
                standard_threshold=int(policy_data["standard_threshold"]),
                critical_threshold=int(policy_data["critical_threshold"]),
                revision_threshold=int(policy_data["revision_threshold"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise DomainConflictError("Revision confidence policy snapshot is invalid") from error
        validated, field_assessments, _ = cls(session, policy, commit=commit).score_run(
            assessment.verification_run_id
        )
        if validated.id != assessment.id:
            raise DomainConflictError("Revision confidence identity mismatch")
        return field_assessments

    def _save(self) -> None:
        self.session.commit() if self.commit else self.session.flush()

    def _get_or_build_field_assessment(
        self, verification: FieldVerification
    ) -> tuple[FieldConfidenceAssessment, bool]:
        data = self._field_result(verification)
        existing = self.field_confidence.get_for_policy(verification.id, ConfidencePolicyVersion.V1)
        if existing is not None:
            if not self._field_assessment_matches(existing, data):
                raise DomainConflictError(
                    "Persisted field confidence output or inputs fail integrity validation"
                )
            return existing, False
        assessment = FieldConfidenceAssessment(**data)
        self.field_confidence.add(assessment)
        return assessment, True

    def _field_result(self, verification: FieldVerification) -> dict[str, Any]:
        endpoint_sets = self._endpoint_sets(verification)
        criticality = classify_field_criticality(verification.candidate_field_path_snapshot)
        base_score = self._base_score(verification)

        support_components = [
            self._component(
                "additional_authoritative_support_endpoint",
                max(len(endpoint_sets[("supports", "authoritative")]) - 1, 0),
                3,
                6,
            ),
            self._component(
                "official_supporting_support_endpoint",
                len(endpoint_sets[("supports", "official")]),
                2,
                4,
            ),
            self._component(
                "secondary_support_endpoint",
                len(endpoint_sets[("supports", "secondary")]),
                1,
                2,
            ),
        ]
        conflict_components = [
            self._component(
                "secondary_conflict_endpoint",
                len(endpoint_sets[("conflicts", "secondary")]),
                -5,
                -10,
            ),
            self._component(
                "official_supporting_conflict_endpoint",
                len(endpoint_sets[("conflicts", "official")]),
                -12,
                -24,
            ),
        ]
        if base_score is None:
            score = None
        else:
            score = base_score + sum(
                item["points"] for item in support_components + conflict_components
            )
            score = max(0, min(100, score))
            if verification.reason_code == VerificationReasonCode.AUTHORITATIVE_CONFLICT:
                score = min(score, 25)

        extraction_items = self.extraction_evidence.list_evidence_for_field(
            verification.candidate_field_id
        )
        usable_endpoint_ids = sorted(
            {
                str(endpoint_id)
                for key, values in endpoint_sets.items()
                if key[0] != "context"
                for endpoint_id in values
            }
        )
        context_endpoint_ids = sorted(str(item) for item in endpoint_sets[("context", "all")])
        authoritative_support = bool(endpoint_sets[("supports", "authoritative")])
        reasons = self._field_review_reasons(
            verification, criticality, score, authoritative_support
        )
        priority = self._field_priority(verification, criticality, score, reasons)
        breakdown: dict[str, Any] = {
            "policy": self.policy.as_dict(),
            "base": {
                "outcome": verification.outcome.value,
                "reason": verification.reason_code.value,
                "points": base_score,
            },
            "support": support_components,
            "conflicts": conflict_components,
            "completeness": {
                "verification_evidence_count": len(verification.assessments),
                "distinct_usable_source_endpoints": len(usable_endpoint_ids),
                "distinct_context_only_source_endpoints": len(context_endpoint_ids),
                "authoritative_support_present": authoritative_support,
                "extraction_evidence_available": bool(extraction_items),
            },
            "authoritative_conflict_cap": 25,
            "final_score": score,
        }
        fingerprint = self._hash(
            {
                "policy": self.policy.as_dict(),
                "field_verification": self._field_facts(verification),
                "criticality": criticality.value,
                "extraction_evidence": sorted(
                    {f"{item.id}:{item.evidence_hash}" for item in extraction_items}
                ),
            }
        )
        return {
            "field_verification_id": verification.id,
            "policy_version": ConfidencePolicyVersion.V1,
            "input_hash": fingerprint,
            "score": score,
            "criticality": criticality,
            "review_required": bool(reasons),
            "review_priority": priority,
            "review_reason_codes": [item.value for item in reasons],
            "component_breakdown": breakdown,
        }

    def _revision_result(
        self, run, field_assessments: list[FieldConfidenceAssessment]
    ) -> dict[str, Any]:
        revision = self.revisions.get(run.candidate_revision_id)
        if revision is None:
            raise DomainConflictError("Verification run revision is unavailable")
        if revision.revision_hash != run.candidate_revision_hash_snapshot:
            raise DomainConflictError("Verification run revision snapshot mismatch")

        finalized_count = len(field_assessments)
        coverage_exact = Decimal(finalized_count) / Decimal(run.fields_total)
        coverage_ratio = coverage_exact.quantize(Decimal("0.0001"))
        scored = [item for item in field_assessments if item.score is not None]
        weighted_sum = sum(
            Decimal(item.score) * (2 if item.criticality == FieldCriticality.CRITICAL else 1)
            for item in scored
        )
        total_weight = sum(
            2 if item.criticality == FieldCriticality.CRITICAL else 1 for item in scored
        )
        weighted_average = weighted_sum / Decimal(total_weight) if total_weight else None
        score = (
            int((weighted_average * coverage_exact).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if weighted_average is not None
            else None
        )

        critical_paths = {
            field.id
            for field in revision.fields
            if classify_field_criticality(field.field_path) == FieldCriticality.CRITICAL
        }
        field_requiring_review = [item for item in field_assessments if item.review_required]
        critical_requiring_review = [
            item for item in field_requiring_review if item.criticality == FieldCriticality.CRITICAL
        ]
        reasons = self._revision_review_reasons(run, field_assessments, score)
        priority = self._revision_priority(run, field_assessments, reasons)
        field_rows = sorted(
            (
                {
                    "field_confidence_assessment_id": str(item.id),
                    "field_verification_id": str(item.field_verification_id),
                    "criticality": item.criticality.value,
                    "score": item.score,
                    "weight": 2 if item.criticality == FieldCriticality.CRITICAL else 1,
                    "review_required": item.review_required,
                    "review_priority": item.review_priority.value,
                }
                for item in field_assessments
            ),
            key=lambda item: item["field_verification_id"],
        )
        breakdown = {
            "policy": self.policy.as_dict(),
            "aggregation": {
                "method": "weighted_field_average_times_coverage",
                "critical_weight": 2,
                "standard_weight": 1,
                "weighted_sum": str(weighted_sum),
                "total_weight": total_weight,
                "weighted_field_average": (
                    str(weighted_average) if weighted_average is not None else None
                ),
                "coverage_numerator": finalized_count,
                "coverage_denominator": run.fields_total,
                "coverage_ratio": str(coverage_ratio),
            },
            "fields": field_rows,
            "final_score": score,
        }
        fingerprint = self._hash(
            {
                "policy": self.policy.as_dict(),
                "run": {
                    "id": str(run.id),
                    "candidate_revision_id": str(run.candidate_revision_id),
                    "candidate_revision_hash_snapshot": run.candidate_revision_hash_snapshot,
                    "status": run.status.value,
                    "fields_total": run.fields_total,
                },
                "field_assessments": [
                    {
                        "id": str(item.id),
                        "input_hash": item.input_hash,
                        "score": item.score,
                        "criticality": item.criticality.value,
                        "review_required": item.review_required,
                        "review_priority": item.review_priority.value,
                        "review_reason_codes": item.review_reason_codes,
                    }
                    for item in sorted(field_assessments, key=lambda value: str(value.id))
                ],
            }
        )
        return {
            "verification_run_id": run.id,
            "candidate_revision_id": run.candidate_revision_id,
            "policy_version": ConfidencePolicyVersion.V1,
            "input_hash": fingerprint,
            "score": score,
            "coverage_ratio": coverage_ratio,
            "fields_total": run.fields_total,
            "fields_scored": len(scored),
            "fields_not_applicable": finalized_count - len(scored),
            "critical_fields_total": len(critical_paths),
            "critical_fields_requiring_review": len(critical_requiring_review),
            "fields_requiring_review": len(field_requiring_review),
            "review_required": bool(reasons),
            "review_priority": priority,
            "review_reason_codes": [item.value for item in reasons],
            "component_breakdown": breakdown,
        }

    def _endpoint_sets(
        self, verification: FieldVerification
    ) -> dict[tuple[str, str], set[uuid.UUID]]:
        result = {
            (kind, source): set()
            for kind in ("supports", "conflicts")
            for source in ("authoritative", "official", "secondary")
        }
        result[("context", "all")] = set()
        source_names = {
            SourceClass.AUTHORITATIVE_OFFICIAL: "authoritative",
            SourceClass.OFFICIAL_SUPPORTING: "official",
            SourceClass.SECONDARY_DISCOVERY_ONLY: "secondary",
        }
        for assessment in verification.assessments:
            document = assessment.evidence.source_document
            endpoint = document.source_endpoint
            if endpoint is None:
                raise DomainConflictError("Verification evidence provenance is unavailable")
            if endpoint.source_class != assessment.source_class_snapshot:
                raise DomainConflictError("Verification evidence source-class provenance mismatch")
            if assessment.assessment == EvidenceAssessmentType.CONTEXT_ONLY:
                result[("context", "all")].add(endpoint.id)
                continue
            kind = (
                "supports"
                if assessment.assessment == EvidenceAssessmentType.SUPPORTS
                else "conflicts"
            )
            result[(kind, source_names[endpoint.source_class])].add(endpoint.id)
        return result

    def _field_facts(self, verification: FieldVerification) -> dict[str, Any]:
        return {
            "id": str(verification.id),
            "run_id": str(verification.verification_run_id),
            "candidate_field_id": str(verification.candidate_field_id),
            "field_path": verification.candidate_field_path_snapshot,
            "value": verification.candidate_field_value_snapshot,
            "value_type": verification.candidate_field_type_snapshot.value,
            "outcome": verification.outcome.value,
            "reason_code": verification.reason_code.value,
            "assessments": sorted(
                (
                    {
                        "id": str(item.id),
                        "evidence_id": str(item.evidence_id),
                        "evidence_hash": item.evidence.evidence_hash,
                        "source_document_id": str(item.evidence.source_document_id),
                        "source_document_hash": item.evidence.source_document.content_hash,
                        "source_endpoint_id": str(item.evidence.source_document.source_endpoint_id),
                        "source_class": (
                            item.evidence.source_document.source_endpoint.source_class.value
                        ),
                        "assessment": item.assessment.value,
                        "asserted_value": item.asserted_value,
                        "asserted_value_type": (
                            item.asserted_value_type.value
                            if item.asserted_value_type is not None
                            else None
                        ),
                    }
                    for item in verification.assessments
                ),
                key=lambda item: (item["evidence_id"], item["assessment"]),
            ),
        }

    @staticmethod
    def _base_score(verification: FieldVerification) -> int | None:
        if verification.outcome == FieldVerificationOutcome.NOT_APPLICABLE:
            return None
        anchors = {
            VerificationReasonCode.AUTHORITATIVE_SUPPORT: 90,
            VerificationReasonCode.AUTHORITATIVE_CONFLICT: 15,
            VerificationReasonCode.SOURCE_CONFLICT: 35,
            VerificationReasonCode.NO_EVIDENCE: 20,
            VerificationReasonCode.ONLY_SECONDARY_EVIDENCE: 45,
            VerificationReasonCode.INSUFFICIENT_SUPPORT: 40,
        }
        if verification.reason_code not in anchors:
            raise DomainConflictError("Field verification reason has no V1 score anchor")
        return anchors[verification.reason_code]

    @staticmethod
    def _component(name: str, count: int, points_each: int, cap: int) -> dict[str, int | str]:
        raw = count * points_each
        points = min(raw, cap) if points_each > 0 else max(raw, cap)
        return {
            "component": name,
            "distinct_endpoint_count": count,
            "points_each": points_each,
            "cap": cap,
            "points": points,
        }

    def _field_review_reasons(
        self,
        verification: FieldVerification,
        criticality: FieldCriticality,
        score: int | None,
        authoritative_support: bool,
    ) -> list[ReviewReasonCode]:
        reasons: list[ReviewReasonCode] = []
        reason_mapping = {
            VerificationReasonCode.AUTHORITATIVE_CONFLICT: ReviewReasonCode.AUTHORITATIVE_CONFLICT,
            VerificationReasonCode.SOURCE_CONFLICT: ReviewReasonCode.SOURCE_CONFLICT,
            VerificationReasonCode.NO_EVIDENCE: ReviewReasonCode.INSUFFICIENT_EVIDENCE,
            VerificationReasonCode.INSUFFICIENT_SUPPORT: ReviewReasonCode.INSUFFICIENT_EVIDENCE,
            VerificationReasonCode.ONLY_SECONDARY_EVIDENCE: (
                ReviewReasonCode.ONLY_SECONDARY_EVIDENCE
            ),
        }
        if verification.reason_code in reason_mapping:
            reasons.append(reason_mapping[verification.reason_code])
        if score is not None:
            if criticality == FieldCriticality.CRITICAL:
                if score < self.policy.critical_threshold:
                    reasons.append(ReviewReasonCode.CRITICAL_FIELD_BELOW_THRESHOLD)
                if not authoritative_support:
                    reasons.append(ReviewReasonCode.CRITICAL_FIELD_NO_AUTHORITATIVE_SUPPORT)
            elif score < self.policy.standard_threshold:
                reasons.append(ReviewReasonCode.FIELD_SCORE_BELOW_THRESHOLD)
        return self._ordered_reasons(reasons)

    @staticmethod
    def _field_priority(
        verification: FieldVerification,
        criticality: FieldCriticality,
        score: int | None,
        reasons: list[ReviewReasonCode],
    ) -> ReviewPriority:
        if not reasons:
            return ReviewPriority.NONE
        if (
            verification.reason_code == VerificationReasonCode.AUTHORITATIVE_CONFLICT
            and criticality == FieldCriticality.CRITICAL
        ):
            return ReviewPriority.CRITICAL
        if (
            verification.reason_code == VerificationReasonCode.AUTHORITATIVE_CONFLICT
            or criticality == FieldCriticality.CRITICAL
            and (
                ReviewReasonCode.SOURCE_CONFLICT in reasons
                or ReviewReasonCode.CRITICAL_FIELD_NO_AUTHORITATIVE_SUPPORT in reasons
                or score is not None
                and score < 50
            )
        ):
            return ReviewPriority.HIGH
        return ReviewPriority.NORMAL

    def _revision_review_reasons(
        self,
        run,
        field_assessments: list[FieldConfidenceAssessment],
        score: int | None,
    ) -> list[ReviewReasonCode]:
        reasons = [
            ReviewReasonCode(value)
            for item in field_assessments
            for value in item.review_reason_codes
        ]
        if run.status == VerificationRunStatus.PARTIAL:
            reasons.append(ReviewReasonCode.PARTIAL_VERIFICATION)
        if score is None or score < self.policy.revision_threshold:
            reasons.append(ReviewReasonCode.REVISION_SCORE_BELOW_THRESHOLD)
        return self._ordered_reasons(reasons)

    @staticmethod
    def _revision_priority(
        run,
        field_assessments: list[FieldConfidenceAssessment],
        reasons: list[ReviewReasonCode],
    ) -> ReviewPriority:
        priority = max(
            (item.review_priority for item in field_assessments),
            key=lambda item: PRIORITY_RANK[item],
            default=ReviewPriority.NONE,
        )
        if run.status == VerificationRunStatus.PARTIAL:
            priority = max(priority, ReviewPriority.NORMAL, key=lambda item: PRIORITY_RANK[item])
        if reasons and priority == ReviewPriority.NONE:
            return ReviewPriority.NORMAL
        return priority

    def _get_finalized_field(self, verification_id: uuid.UUID) -> FieldVerification:
        verification = self.fields.get(verification_id)
        if verification is None:
            raise ResourceNotFoundError("Field verification not found")
        if verification.status != FieldVerificationStatus.FINALIZED:
            raise DomainConflictError("Only finalized field verifications can be scored")
        return verification

    def _get_scorable_run(self, run_id: uuid.UUID):
        run = self.runs.get(run_id)
        if run is None:
            raise ResourceNotFoundError("Verification run not found")
        if run.status not in {
            VerificationRunStatus.COMPLETED,
            VerificationRunStatus.PARTIAL,
        }:
            raise DomainConflictError("Confidence requires a COMPLETED or PARTIAL verification run")
        return run

    def _assert_fingerprint(self, existing_hash: str, verification: FieldVerification) -> None:
        existing = self.field_confidence.get_for_policy(verification.id, ConfidencePolicyVersion.V1)
        data = self._field_result(verification)
        if (
            existing is None
            or existing_hash != data["input_hash"]
            or not self._field_assessment_matches(existing, data)
        ):
            raise DomainConflictError(
                "Persisted verification facts differ from the existing confidence assessment"
            )

    @staticmethod
    def _field_assessment_matches(
        existing: FieldConfidenceAssessment, data: dict[str, Any]
    ) -> bool:
        return all(
            getattr(existing, key) == value
            for key, value in data.items()
            if key != "field_verification_id"
        )

    @staticmethod
    def _revision_assessment_matches(
        existing: RevisionConfidenceAssessment, data: dict[str, Any]
    ) -> bool:
        return all(
            getattr(existing, key) == value
            for key, value in data.items()
            if key not in {"verification_run_id", "candidate_revision_id"}
        )

    def _list_field_assessments(self, run_id: uuid.UUID) -> list[FieldConfidenceAssessment]:
        return self.field_confidence.list_for_run(run_id, ConfidencePolicyVersion.V1)

    @staticmethod
    def _ordered_reasons(
        reasons: list[ReviewReasonCode],
    ) -> list[ReviewReasonCode]:
        selected = set(reasons)
        return [item for item in ReviewReasonCode if item in selected]

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()
