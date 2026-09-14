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
from app.services.exceptions import DomainConflictError
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
            posts = (
                revision.advertisement_revision.posts
                if revision.advertisement_revision is not None
                else []
            )
            post_by_key = {post.post_key: post for post in posts}
            item_groups: dict[str | None, list[Any]] = {}
            for item in case.items:
                post_key = ReviewService._post_key(item.field_path_snapshot)
                item_groups.setdefault(post_key, []).append(item)
            for post_key, grouped_items in item_groups.items():
                post = post_by_key.get(post_key)
                reasons = sorted(
                    {
                        reason
                        for item in grouped_items
                        for reason in item.review_reason_codes_snapshot
                    }
                    | set(case.revision_review_reason_codes_snapshot)
                )
                scores = [
                    item.confidence_score_snapshot
                    for item in grouped_items
                    if item.confidence_score_snapshot is not None
                ]
                entries.append({
                    "id": case.id,
                    "short_id": str(case.id).split("-")[0],
                    "candidate_name": candidate.display_name,
                    "candidate_key": candidate.candidate_key,
                    "advertisement_title": candidate.display_name,
                    "post_key": post_key,
                    "post_name": post.name if post is not None else "Advertisement-wide review",
                    "authority_name": candidate.recruiting_authority.name,
                    "organization": self._organization(revision),
                    "important_fields": self._important_post_fields(post),
                    "review_reasons": [humanize(reason) for reason in reasons],
                    "status": case.status.value,
                    "priority": case.priority.value,
                    "score": min(scores) if scores else case.revision_score_snapshot,
                    "policy_version": case.policy_version.value,
                    "pending_items": sum(
                        item.status == ReviewItemStatus.PENDING for item in grouped_items
                    ),
                    "total_items": len(grouped_items),
                    "opened_at": case.opened_at,
                })
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

    def case(self, case_id: uuid.UUID, *, focus_post_key: str | None = None) -> dict[str, Any]:
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
        if focus_post_key is not None and focus_post_key not in post_names:
            raise DomainConflictError("The selected Post is not part of this review case")

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
        all_review_groups = review_groups
        if focus_post_key is not None:
            review_groups = [
                group
                for group in all_review_groups
                if group["key"] in {None, focus_post_key}
            ]
        focused_post = next(
            (post for post in posts if post.post_key == focus_post_key), None
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
                "organization": self._organization(revision),
            },
            "focused_post": (
                {
                    "key": focused_post.post_key,
                    "name": focused_post.name,
                    "important_fields": self._important_post_fields(focused_post),
                }
                if focused_post is not None
                else None
            ),
            "post_links": [
                {"key": post.post_key, "name": post.name}
                for post in posts
                if any(
                    group["key"] == post.post_key and group["items"]
                    for group in all_review_groups
                )
            ],
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

    @staticmethod
    def _organization(revision: RecruitmentCandidateRevision) -> str:
        by_path = {field.field_path: field.value for field in revision.fields}
        for path in ("organization.unit", "organization.name", "department.name"):
            value = by_path.get(path)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())
        return revision.recruitment_candidate.recruiting_authority.name

    @staticmethod
    def _important_post_fields(post: RecruitmentPost | None) -> list[dict[str, str]]:
        if post is None:
            return []
        priority = {
            "vacancies.total": 0,
            "qualification.minimum": 1,
            "age.minimum": 2,
            "age.maximum": 3,
            "experience.minimum_months": 4,
            "pay.scale": 5,
            "salary.minimum": 6,
            "salary.maximum": 7,
        }
        facts = sorted(
            (fact for fact in post.facts if fact.fact_key in priority),
            key=lambda fact: priority[fact.fact_key],
        )
        return [
            {
                "label": humanize(fact.fact_key.replace(".", "_")),
                "value": display_value(fact.candidate_field.value),
            }
            for fact in facts
        ]

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
