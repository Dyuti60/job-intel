import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.candidates import (
    AdvertisementRevision,
    RecruitmentCandidate,
    RecruitmentCandidateRevision,
    RecruitmentPost,
)
from app.models.confidence import ReviewPriority
from app.models.discovery import SourceDocument
from app.models.evidence import CandidateFieldEvidence, Evidence
from app.models.review import ReviewCaseStatus, ReviewItemScope, ReviewItemStatus
from app.models.source_registry import SourceEndpoint
from app.models.verification import FieldVerification, VerificationEvidenceAssessment
from app.services.review import ReviewService


def humanize(value: str) -> str:
    return value.replace("_", " ").title()


def display_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    return str(value)


def breakdown_rows(value: Any, prefix: str = "") -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            label = humanize(str(key))
            path = f"{prefix} / {label}" if prefix else label
            rows.extend(breakdown_rows(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value, start=1):
            rows.extend(breakdown_rows(child, f"{prefix} #{index}"))
    else:
        rendered = display_value(value)
        if prefix.endswith("Points") and isinstance(value, (int, float)) and value > 0:
            rendered = f"+{value}"
        rows.append({"label": prefix, "value": rendered})
    return rows


class ReviewCaseViewService:
    """Build read-only UI view models without moving domain decisions into templates."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.review = ReviewService(session)

    def queue(
        self,
        *,
        status: ReviewCaseStatus | None,
        priority: ReviewPriority | None,
    ) -> dict[str, Any]:
        if status is None:
            cases = [
                *self.review.list_cases(
                    status=ReviewCaseStatus.QUEUED,
                    priority=priority,
                    candidate_revision_id=None,
                    verification_run_id=None,
                    offset=0,
                    limit=500,
                ),
                *self.review.list_cases(
                    status=ReviewCaseStatus.IN_REVIEW,
                    priority=priority,
                    candidate_revision_id=None,
                    verification_run_id=None,
                    offset=0,
                    limit=500,
                ),
            ]
            rank = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "NONE": 3}
            cases.sort(key=lambda case: (rank[case.priority.value], case.opened_at, str(case.id)))
        else:
            cases = self.review.list_cases(
                status=status,
                priority=priority,
                candidate_revision_id=None,
                verification_run_id=None,
                offset=0,
                limit=500,
            )

        entries = []
        for case in cases:
            revision = self._revision(case.candidate_revision_id)
            candidate = revision.recruitment_candidate
            pending = sum(item.status == ReviewItemStatus.PENDING for item in case.items)
            entries.append(
                {
                    "id": case.id,
                    "short_id": str(case.id).split("-")[0],
                    "candidate_name": candidate.display_name,
                    "candidate_key": candidate.candidate_key,
                    "status": case.status.value,
                    "priority": case.priority.value,
                    "score": case.revision_score_snapshot,
                    "policy_version": case.policy_version.value,
                    "pending_items": pending,
                    "total_items": len(case.items),
                    "opened_at": case.opened_at,
                }
            )
        all_cases = self.review.list_cases(
            status=None,
            priority=None,
            candidate_revision_id=None,
            verification_run_id=None,
            offset=0,
            limit=500,
        )
        return {
            "cases": entries,
            "counts": {
                "queued": sum(case.status == ReviewCaseStatus.QUEUED for case in all_cases),
                "critical": sum(
                    case.status in {ReviewCaseStatus.QUEUED, ReviewCaseStatus.IN_REVIEW}
                    and case.priority.value == "CRITICAL"
                    for case in all_cases
                ),
                "high": sum(
                    case.status in {ReviewCaseStatus.QUEUED, ReviewCaseStatus.IN_REVIEW}
                    and case.priority.value == "HIGH"
                    for case in all_cases
                ),
                "in_review": sum(case.status == ReviewCaseStatus.IN_REVIEW for case in all_cases),
            },
        }

    def case(self, case_id: uuid.UUID) -> dict[str, Any]:
        review_case = self.review.get_case(case_id)
        revision = self._revision(review_case.candidate_revision_id)
        candidate = revision.recruitment_candidate
        authority = candidate.recruiting_authority
        source_document = revision.source_document
        revision_confidence = review_case.revision_confidence_assessment
        posts = (
            revision.advertisement_revision.posts
            if revision.advertisement_revision is not None
            else []
        )
        post_names = {post.post_key: post.name for post in posts}

        items = []
        for item in review_case.items:
            item_view: dict[str, Any] = {
                "id": item.id,
                "scope": item.scope.value,
                "status": item.status.value,
                "priority": item.priority.value,
                "policy_version": item.policy_version.value,
                "field_path": item.field_path_snapshot,
                "value_type": (
                    item.candidate_value_type_snapshot.value
                    if item.candidate_value_type_snapshot is not None
                    else None
                ),
                "original_value": item.candidate_value_snapshot,
                "original_value_display": display_value(item.candidate_value_snapshot),
                "confidence_score": item.confidence_score_snapshot,
                "review_reasons": [
                    {"code": reason, "label": humanize(reason)}
                    for reason in item.review_reason_codes_snapshot
                ],
                "breakdown": breakdown_rows(item.component_breakdown_snapshot),
                "decision": self._decision(item),
                "criticality": None,
                "extraction_evidence": [],
                "verification": None,
                "post_key": ReviewService._post_key(item.field_path_snapshot),
            }
            item_view["post_name"] = post_names.get(item_view["post_key"])
            if item.scope == ReviewItemScope.FIELD:
                confidence = item.field_confidence_assessment
                item_view["criticality"] = confidence.criticality.value
                field_verification = self._field_verification(confidence.field_verification_id)
                item_view["extraction_evidence"] = self._extraction_evidence(
                    item.candidate_field_id
                )
                item_view["verification"] = {
                    "id": field_verification.id,
                    "outcome": (
                        field_verification.outcome.value
                        if field_verification.outcome is not None
                        else None
                    ),
                    "reason": (
                        field_verification.reason_code.value
                        if field_verification.reason_code is not None
                        else None
                    ),
                    "finding": field_verification.finding_summary,
                    "assessments": [
                        self._verification_assessment(assessment)
                        for assessment in field_verification.assessments
                    ],
                }
            items.append(item_view)

        resolved = sum(item["status"] == ReviewItemStatus.RESOLVED.value for item in items)
        advertisement_items = [item for item in items if item["post_key"] is None]
        review_groups = []
        if advertisement_items:
            review_groups.append(
                {
                    "scope": "ADVERTISEMENT",
                    "key": None,
                    "name": "Advertisement",
                    "items": advertisement_items,
                }
            )
        for post in posts:
            review_groups.append(
                {
                    "scope": "POST",
                    "key": post.post_key,
                    "name": post.name,
                    "items": [item for item in items if item["post_key"] == post.post_key],
                }
            )
        if not review_groups:
            review_groups.append(
                {"scope": "ADVERTISEMENT", "key": None, "name": "Advertisement", "items": items}
            )
        result = {
            "case": review_case,
            "case_id": review_case.id,
            "status": review_case.status.value,
            "priority": review_case.priority.value,
            "policy_version": review_case.policy_version.value,
            "score": review_case.revision_score_snapshot,
            "reasons": [
                {"code": reason, "label": humanize(reason)}
                for reason in review_case.revision_review_reason_codes_snapshot
            ],
            "breakdown": breakdown_rows(review_case.component_breakdown_snapshot),
            "coverage_ratio": str(revision_confidence.coverage_ratio),
            "outcome": review_case.outcome.value if review_case.outcome is not None else None,
            "resolved_items": resolved,
            "total_items": len(items),
            "candidate": {
                "id": candidate.id,
                "display_name": candidate.display_name,
                "candidate_key": candidate.candidate_key,
                "revision_number": revision.revision_number,
                "authority_name": authority.name,
                "authority_code": authority.code,
                "source_document_url": source_document.document_url,
                "source_document_type": source_document.document_type.value,
            },
            "items": items,
            "review_groups": review_groups,
            "projection": None,
        }
        if review_case.status == ReviewCaseStatus.RESOLVED:
            projection = self.review.approved_projection(review_case.id)
            result["projection"] = {
                **projection,
                "outcome": projection["outcome"].value,
                "fields": [
                    {
                        **field,
                        "value_type": field["value_type"].value,
                        "original_value_display": display_value(field["original_value"]),
                        "effective_value_display": display_value(field["effective_value"]),
                    }
                    for field in projection["fields"]
                ],
            }
        return result

    def _revision(self, revision_id: uuid.UUID) -> RecruitmentCandidateRevision:
        revision = self.session.scalar(
            select(RecruitmentCandidateRevision)
            .options(
                selectinload(RecruitmentCandidateRevision.fields),
                selectinload(RecruitmentCandidateRevision.recruitment_candidate).selectinload(
                    RecruitmentCandidate.recruiting_authority
                ),
                selectinload(RecruitmentCandidateRevision.source_document)
                .selectinload(SourceDocument.source_endpoint)
                .selectinload(SourceEndpoint.recruiting_authority),
                selectinload(RecruitmentCandidateRevision.advertisement_revision)
                .selectinload(AdvertisementRevision.posts)
                .selectinload(RecruitmentPost.facts),
            )
            .where(RecruitmentCandidateRevision.id == revision_id)
        )
        if revision is None:
            raise RuntimeError("Review case candidate revision is unavailable")
        return revision

    def _field_verification(self, verification_id: uuid.UUID) -> FieldVerification:
        verification = self.session.scalar(
            select(FieldVerification)
            .options(
                selectinload(FieldVerification.assessments)
                .selectinload(VerificationEvidenceAssessment.evidence)
                .selectinload(Evidence.source_document)
                .selectinload(SourceDocument.source_endpoint)
                .selectinload(SourceEndpoint.recruiting_authority)
            )
            .where(FieldVerification.id == verification_id)
        )
        if verification is None:
            raise RuntimeError("Review field verification is unavailable")
        return verification

    def _extraction_evidence(self, candidate_field_id: uuid.UUID | None) -> list[dict[str, Any]]:
        if candidate_field_id is None:
            return []
        records = self.session.scalars(
            select(Evidence)
            .join(CandidateFieldEvidence, CandidateFieldEvidence.evidence_id == Evidence.id)
            .options(
                selectinload(Evidence.source_document)
                .selectinload(SourceDocument.source_endpoint)
                .selectinload(SourceEndpoint.recruiting_authority)
            )
            .where(CandidateFieldEvidence.candidate_field_id == candidate_field_id)
            .order_by(Evidence.created_at, Evidence.id)
        )
        return [self._evidence(record) for record in records]

    def _verification_assessment(
        self, assessment: VerificationEvidenceAssessment
    ) -> dict[str, Any]:
        return {
            "id": assessment.id,
            "assessment": assessment.assessment.value,
            "asserted_value": display_value(assessment.asserted_value),
            "asserted_value_type": (
                assessment.asserted_value_type.value
                if assessment.asserted_value_type is not None
                else None
            ),
            "source_class": assessment.source_class_snapshot.value,
            "note": assessment.assessment_note,
            "evidence": self._evidence(assessment.evidence),
        }

    @staticmethod
    def _evidence(evidence: Evidence) -> dict[str, Any]:
        document = evidence.source_document
        endpoint = document.source_endpoint
        authority = endpoint.recruiting_authority
        return {
            "id": evidence.id,
            "type": evidence.evidence_type.value,
            "excerpt": evidence.excerpt,
            "context": evidence.context,
            "locator": evidence.source_locator,
            "document_url": document.document_url,
            "document_type": document.document_type.value,
            "endpoint_name": endpoint.name,
            "source_class": endpoint.source_class.value,
            "authority_name": authority.name,
        }

    @staticmethod
    def _decision(item: Any) -> dict[str, Any] | None:
        decision = item.decision
        if decision is None:
            return None
        return {
            "id": decision.id,
            "decision": decision.decision.value,
            "reviewer_identifier": decision.reviewer_identifier,
            "note": decision.decision_note,
            "evidence_note": decision.evidence_note,
            "decided_at": decision.decided_at,
            "original_value": display_value(decision.original_value_snapshot),
            "corrected_value": display_value(decision.corrected_value),
            "corrected_value_type": (
                decision.corrected_value_type.value
                if decision.corrected_value_type is not None
                else None
            ),
        }
