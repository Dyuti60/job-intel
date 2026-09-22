import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.candidates import (
    AdvertisementRevision,
    AdvertisementSplitStatus,
    CandidateField,
    CandidateValueType,
    RecruitmentCandidate,
    RecruitmentCandidateRevision,
    RecruitmentPost,
)
from app.models.confidence import ReviewPriority
from app.models.discovery import SourceDocument
from app.models.evidence import CandidateFieldEvidence, Evidence
from app.models.master import (
    MasterPost,
    RecruitmentMaster,
    RecruitmentMasterRevision,
    RecruitmentMasterStatus,
)
from app.models.review import (
    ReviewCaseStatus,
    ReviewDecisionType,
    ReviewItemScope,
    ReviewItemStatus,
)
from app.models.source_registry import SourceEndpoint
from app.models.verification import FieldVerification, VerificationEvidenceAssessment
from app.repositories.confidence import FieldConfidenceRepository
from app.services.exceptions import DomainConflictError
from app.services.master import MasterPublisherService
from app.services.post_identity import canonical_post_name
from app.services.public_readiness import candidate_post_readiness
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
        self._published_post_cache: dict[uuid.UUID, MasterPost | None] = {}

    def queue(
        self,
        *,
        status: ReviewCaseStatus | None,
        priority: ReviewPriority | None,
    ) -> dict[str, Any]:
        def cases_for(
            state: ReviewCaseStatus | None, selected_priority: ReviewPriority | None
        ) -> list[Any]:
            cases = []
            while True:
                batch = self.review.list_cases(
                    status=state,
                    priority=selected_priority,
                    candidate_revision_id=None,
                    verification_run_id=None,
                    offset=len(cases),
                    limit=500,
                )
                cases.extend(batch)
                if len(batch) < 500:
                    return cases

        if status is None:
            cases = [
                *cases_for(ReviewCaseStatus.QUEUED, priority),
                *cases_for(ReviewCaseStatus.IN_REVIEW, priority),
            ]
            rank = {"CRITICAL": 0, "HIGH": 1, "NORMAL": 2, "NONE": 3}
            cases.sort(key=lambda case: (rank[case.priority.value], case.opened_at, str(case.id)))
        elif status == ReviewCaseStatus.RESOLVED:
            cases = [
                *cases_for(ReviewCaseStatus.IN_REVIEW, priority),
                *cases_for(ReviewCaseStatus.RESOLVED, priority),
            ]
        else:
            cases = cases_for(status, priority)

        entries = []
        for case in cases:
            revision = self._revision(case.candidate_revision_id)
            candidate = revision.recruitment_candidate
            entry_groups = self._review_units(case, revision)
            for post, grouped_items in entry_groups:
                post_key = post.post_key if post is not None else None
                scope_outcome = self._scope_outcome(grouped_items)
                if status is None and scope_outcome is not None:
                    continue
                if status == ReviewCaseStatus.RESOLVED and scope_outcome is None:
                    continue
                if status == ReviewCaseStatus.IN_REVIEW and (
                    case.status != ReviewCaseStatus.IN_REVIEW or scope_outcome is not None
                ):
                    continue
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
                readiness = candidate_post_readiness(revision, post)
                entries.append(
                    {
                        "authority_code": candidate.recruiting_authority.code,
                        "id": case.id,
                        "short_id": str(case.id).split("-")[0],
                        "candidate_name": candidate.display_name,
                        "candidate_key": candidate.candidate_key,
                        "advertisement_title": candidate.display_name,
                        "post_key": post_key,
                        "completeness": readiness.status.value,
                        "missing": list(readiness.missing),
                        "post_name": self._post_name(post, case.items)
                        if post is not None
                        else candidate.display_name,
                        "authority_name": candidate.recruiting_authority.name,
                        "organization": self._organization(revision),
                        "important_fields": self._important_post_fields(post),
                        "review_reasons": [humanize(reason) for reason in reasons],
                        "status": "RESOLVED" if scope_outcome is not None else case.status.value,
                        "outcome": scope_outcome,
                        "priority": case.priority.value,
                        "score": min(scores) if scores else case.revision_score_snapshot,
                        "policy_version": case.policy_version.value,
                        "pending_items": sum(
                            item.status == ReviewItemStatus.PENDING for item in grouped_items
                        ),
                        "total_items": len(grouped_items),
                        "opened_at": case.opened_at,
                        "source_refreshed_at": revision.source_document.retrieved_at,
                        "source_document_id": revision.source_document_id,
                        "verified_at": (
                            case.revision_confidence_assessment.verification_run.completed_at
                        ),
                        "published": self._published_post(post),
                        "quick_eligible": post is not None
                        and case.status
                        in {
                            ReviewCaseStatus.QUEUED,
                            ReviewCaseStatus.IN_REVIEW,
                            ReviewCaseStatus.RESOLVED,
                        }
                        and not any(
                            item.decision and item.decision.decision == ReviewDecisionType.REJECT
                            for item in grouped_items
                        ),
                    }
                )
        all_cases = cases_for(None, None)
        all_units = [
            (case, post, grouped_items, self._scope_outcome(grouped_items))
            for case in all_cases
            for post, grouped_items in self._review_units(
                case, self._revision(case.candidate_revision_id)
            )
        ]
        approved_outcomes = {"APPROVED", "APPROVED_WITH_CORRECTIONS"}
        return {
            "cases": entries,
            "counts": {
                "review_required": sum(
                    outcome is None and case.status == ReviewCaseStatus.QUEUED
                    for case, _post, _items, outcome in all_units
                ),
                "in_review": sum(
                    outcome is None and case.status == ReviewCaseStatus.IN_REVIEW
                    for case, _post, _items, outcome in all_units
                ),
                "approved": sum(
                    outcome in approved_outcomes for _case, _post, _items, outcome in all_units
                ),
                "rejected": sum(
                    outcome == "REJECTED" for _case, _post, _items, outcome in all_units
                ),
                "published": sum(
                    self._published_post(post) is not None
                    for _case, post, _items, _outcome in all_units
                    if post is not None
                ),
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
        explicit_posts = (
            posts
            if revision.advertisement_revision is not None
            and revision.advertisement_revision.split_status == AdvertisementSplitStatus.EXPLICIT
            else []
        )
        post_names = {post.post_key: self._post_name(post, review_case.items) for post in posts}
        if focus_post_key is not None and focus_post_key not in post_names:
            raise DomainConflictError("The selected Post is not part of this review case")

        items = []
        for item in review_case.items:
            item_view: dict[str, Any] = {
                "id": item.id,
                "candidate_field_id": item.candidate_field_id,
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
                item_view["verification"] = self._verification_view(field_verification)
            items.append(item_view)

        resolved = sum(item["status"] == ReviewItemStatus.RESOLVED.value for item in items)
        advertisement_items = [item for item in items if item["post_key"] is None]
        post_groups = [
            {
                "scope": "POST",
                "key": post.post_key,
                "name": post_names[post.post_key],
                "items": [item for item in items if item["post_key"] == post.post_key],
            }
            for post in explicit_posts
            if advertisement_items or any(item["post_key"] == post.post_key for item in items)
        ]
        affected_post_keys = {group["key"] for group in post_groups}
        if focus_post_key is not None and focus_post_key not in affected_post_keys:
            raise DomainConflictError("The selected Post has no review context in this case")
        if focus_post_key is None and post_groups:
            focus_post_key = post_groups[0]["key"]
        review_groups = []
        if advertisement_items and explicit_posts:
            review_groups.append(
                {
                    "scope": "SHARED",
                    "key": None,
                    "name": "Shared Advertisement review items",
                    "items": advertisement_items,
                }
            )
        review_groups.extend(group for group in post_groups if group["key"] == focus_post_key)
        if not explicit_posts:
            review_groups.append(
                {
                    "scope": "ADVERTISEMENT",
                    "key": None,
                    "name": "Advertisement review",
                    "items": items,
                }
            )
        focused_post = next((post for post in posts if post.post_key == focus_post_key), None)
        focused_items = [item for group in review_groups for item in group["items"]]
        focused_outcome = self._scope_outcome_from_views(focused_items)
        publication = self._publication_view(review_case, focused_post, focused_outcome)
        item_by_field_id = {
            item["candidate_field_id"]: item
            for item in items
            if item["candidate_field_id"] is not None
        }
        confidence_by_field_id = {
            assessment.field_verification.candidate_field_id: assessment
            for assessment in FieldConfidenceRepository(self.session).list_for_run(
                review_case.verification_run_id, review_case.policy_version
            )
        }
        shared_attributes = []
        post_attributes = []
        for field in revision.fields:
            field_post_key = ReviewService._post_key(field.field_path)
            if field_post_key is not None and field_post_key != focus_post_key:
                continue
            attribute = self._attribute(
                field,
                confidence_by_field_id.get(field.id),
                item_by_field_id.get(field.id),
            )
            if field_post_key is None:
                shared_attributes.append(attribute)
            else:
                post_attributes.append(attribute)
        attribute_groups = []
        if focused_post is not None:
            attribute_groups.append(
                {
                    "scope": "POST",
                    "name": "Post-specific attributes",
                    "attributes": post_attributes,
                }
            )
            attribute_groups.append(
                {
                    "scope": "ADVERTISEMENT",
                    "name": "Shared Advertisement attributes",
                    "attributes": shared_attributes,
                }
            )
        else:
            attribute_groups.append(
                {
                    "scope": "ADVERTISEMENT",
                    "name": "Advertisement attributes",
                    "attributes": shared_attributes,
                }
            )
        result = {
            "case": review_case,
            "structure_builder": (
                {
                    "status": revision.advertisement_revision.split_status.value,
                    "reason": revision.advertisement_revision.split_note,
                }
                if revision.advertisement_revision is not None
                and revision.advertisement_revision.split_status
                != AdvertisementSplitStatus.EXPLICIT
                and review_case.status != ReviewCaseStatus.CANCELLED
                else None
            ),
            "structure_audit": revision.extraction_note
            if revision.extraction_method == "HUMAN_POST_STRUCTURE"
            else None,
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
            "focused_outcome": focused_outcome,
            "focused_review_complete": focused_outcome is not None,
            "focused_resolved_items": sum(
                item["status"] == ReviewItemStatus.RESOLVED.value for item in focused_items
            ),
            "focused_total_items": len(focused_items),
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
                    "name": post_names[focused_post.post_key],
                    "important_fields": self._important_post_fields(focused_post),
                }
                if focused_post is not None
                else None
            ),
            "post_links": [{"key": group["key"], "name": group["name"]} for group in post_groups],
            "items": items,
            "review_groups": review_groups,
            "attribute_groups": attribute_groups,
            "revision_items": [item for item in focused_items if item["scope"] == "REVISION"],
            "projection": None,
            "publication": publication,
            "quick_eligible": focused_post is not None
            and review_case.status in {ReviewCaseStatus.QUEUED, ReviewCaseStatus.IN_REVIEW}
            and not any(
                item["decision"] and item["decision"]["decision"] == "REJECT"
                for item in focused_items
            ),
        }
        if focused_post is not None:
            links = result["post_links"]
            index = next(i for i, link in enumerate(links) if link["key"] == focused_post.post_key)
            result["post_navigation"] = {
                "position": index + 1,
                "total": len(links),
                "previous": links[index - 1] if index > 0 else None,
                "next": links[index + 1] if index + 1 < len(links) else None,
                "next_unresolved": next(
                    (
                        link
                        for link in [*links[index + 1 :], *links[:index]]
                        if any(
                            item["status"] != "RESOLVED" and item["post_key"] in {None, link["key"]}
                            for item in items
                        )
                    ),
                    None,
                ),
            }
        if review_case.status == ReviewCaseStatus.RESOLVED:
            projection = self.review.approved_projection(review_case.id)
            projection_fields = projection["fields"]
            if focused_post is not None:
                post_prefix = f"posts.{focused_post.post_key}."
                projection_fields = [
                    field
                    for field in projection_fields
                    if not field["field_path"].startswith("posts.")
                    or field["field_path"].startswith(post_prefix)
                ]
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
                    for field in projection_fields
                ],
            }
        return result

    @staticmethod
    def _post_name(post, items) -> str:
        values = {fact.fact_key: fact.candidate_field.value for fact in post.facts}
        old_unit = next(
            (
                values[key]
                for key in (
                    "organisation.name",
                    "organization.name",
                    "organization.unit",
                    "department.name",
                )
                if key in values
            ),
            "",
        )
        for item in items:
            if ReviewService._post_key(item.field_path_snapshot) != post.post_key:
                continue
            if (
                item.decision is not None
                and item.decision.decision == ReviewDecisionType.CORRECT_AND_APPROVE
            ):
                path = item.field_path_snapshot.split(".", 2)[2]
                values[path] = item.decision.corrected_value
        unit = next(
            (
                values[key]
                for key in (
                    "organisation.name",
                    "organization.name",
                    "organization.unit",
                    "department.name",
                )
                if key in values
            ),
            "",
        )
        return canonical_post_name(
            values.get("name", post.name), unit, previous_organisation=old_unit
        )

    def _review_units(
        self, review_case: Any, revision: RecruitmentCandidateRevision
    ) -> list[tuple[RecruitmentPost | None, list[Any]]]:
        item_groups: dict[str | None, list[Any]] = {}
        for item in review_case.items:
            post_key = ReviewService._post_key(item.field_path_snapshot)
            item_groups.setdefault(post_key, []).append(item)
        advertisement = revision.advertisement_revision
        explicit_posts = (
            advertisement.posts
            if advertisement is not None
            and advertisement.split_status == AdvertisementSplitStatus.EXPLICIT
            else []
        )
        if not explicit_posts:
            return [(None, list(review_case.items))]
        shared_items = item_groups.get(None, [])
        return [
            (post, [*shared_items, *item_groups.get(post.post_key, [])])
            for post in explicit_posts
            if shared_items or item_groups.get(post.post_key)
        ]

    def _published_post(self, post: RecruitmentPost | None) -> MasterPost | None:
        if post is None:
            return None
        if post.id in self._published_post_cache:
            return self._published_post_cache[post.id]
        published = self.session.scalar(
            select(MasterPost)
            .join(
                RecruitmentMasterRevision,
                RecruitmentMasterRevision.id == MasterPost.master_revision_id,
            )
            .join(
                RecruitmentMaster,
                RecruitmentMaster.current_revision_id == RecruitmentMasterRevision.id,
            )
            .where(
                MasterPost.source_recruitment_post_id == post.id,
                RecruitmentMaster.status == RecruitmentMasterStatus.ACTIVE,
            )
        )
        self._published_post_cache[post.id] = published
        return published

    def _publication_view(
        self,
        review_case: Any,
        post: RecruitmentPost | None,
        focused_outcome: str | None,
    ) -> dict[str, Any] | None:
        if post is None:
            return None
        published = self._published_post(post)
        if published is not None:
            return {
                "status": "PUBLISHED",
                "public_id": published.public_id,
                "public_url": f"/jobs/{published.public_id}",
                "blocker": None,
            }
        if focused_outcome not in {"APPROVED", "APPROVED_WITH_CORRECTIONS"}:
            return {
                "status": "BLOCKED",
                "public_id": None,
                "public_url": None,
                "blocker": (
                    "This Post must complete review approval before publication."
                    if focused_outcome is None
                    else "This Post review outcome is not publishable."
                ),
            }
        try:
            MasterPublisherService(self.session).preview_post(
                review_case.revision_confidence_assessment_id, post.post_key
            )
        except DomainConflictError as error:
            return {
                "status": "BLOCKED",
                "public_id": None,
                "public_url": None,
                "blocker": str(error),
            }
        return {
            "status": "READY_TO_PUBLISH",
            "public_id": None,
            "public_url": None,
            "blocker": None,
        }

    def _attribute(
        self,
        field: CandidateField,
        confidence: Any | None,
        review_item: dict[str, Any] | None,
    ) -> dict[str, Any]:
        post_key = ReviewService._post_key(field.field_path)
        relative_path = (
            field.field_path.removeprefix(f"posts.{post_key}.")
            if post_key is not None
            else field.field_path
        )
        if review_item is not None:
            evidence = review_item["extraction_evidence"]
            verification = review_item["verification"]
            breakdown = review_item["breakdown"]
            reasons = review_item["review_reasons"]
            decision = review_item["decision"]
        else:
            evidence = self._extraction_evidence(field.id)
            field_verification = (
                self._field_verification(confidence.field_verification_id)
                if confidence is not None
                else None
            )
            verification = (
                self._verification_view(field_verification)
                if field_verification is not None
                else None
            )
            breakdown = (
                breakdown_rows(confidence.component_breakdown) if confidence is not None else []
            )
            reasons = (
                [
                    {"code": reason, "label": humanize(reason)}
                    for reason in confidence.review_reason_codes
                ]
                if confidence is not None
                else []
            )
            decision = None
        final_value = field.value
        status = "TRUSTED / AUTO-ACCEPTED"
        if decision is not None:
            status = decision["decision"].replace("_", " ")
            if decision["decision"] == ReviewDecisionType.CORRECT_AND_APPROVE.value:
                final_value = decision["corrected_value_raw"]
            elif decision["decision"] == ReviewDecisionType.REJECT.value:
                final_value = None
        elif review_item is not None:
            status = "REVIEW REQUIRED"
        return {
            "candidate_field_id": field.id,
            "review_item_id": review_item["id"] if review_item is not None else None,
            "field_path": field.field_path,
            "relative_path": relative_path,
            "label": self._attribute_label(relative_path, post_key is not None),
            "scope": "POST" if post_key is not None else "ADVERTISEMENT",
            "value_type": field.value_type.value,
            "input_type": self._input_type(field.value_type, field.value),
            "extracted_value": field.value,
            "extracted_value_display": display_value(field.value),
            "form_value": self._form_value(field.value_type, field.value),
            "final_value": final_value,
            "final_value_display": (
                "Not trusted"
                if final_value is None and field.value is not None
                else display_value(final_value)
            ),
            "confidence_score": confidence.score if confidence is not None else None,
            "criticality": confidence.criticality.value if confidence is not None else None,
            "review_required": review_item is not None,
            "actionable": (
                review_item is not None and review_item["status"] == ReviewItemStatus.PENDING.value
            ),
            "status": status,
            "decision": decision,
            "review_reasons": reasons,
            "breakdown": breakdown,
            "extraction_evidence": evidence,
            "verification": verification,
        }

    @staticmethod
    def _attribute_label(relative_path: str, post_scoped: bool) -> str:
        labels = {
            "name": "Post Name",
            "post.name": "Post Name",
            "application.start_date": "Application Start Date",
            "application.end_date": "Application End Date",
            "application.fee": "Application Fee",
            "application.mode": "Application Mode",
            "notification.number": "Advertisement Number",
            "advertisement.number": "Advertisement Number",
            "selection.process": "Selection Process",
            "selection_process": "Selection Process",
            "qualification.minimum": "Minimum Qualification",
            "age.minimum": "Minimum Age",
            "age.maximum": "Maximum Age",
            "experience.minimum": "Minimum Experience",
            "experience.minimum_months": "Minimum Experience (Months)",
            "pay.scale": "Pay Scale",
            "salary.minimum": "Minimum Salary",
            "salary.maximum": "Maximum Salary",
            "organisation.name": "Organisation",
            "organization.name": "Organisation",
            "department.name": "Department",
        }
        if relative_path == "vacancies.total":
            return "Post Vacancies" if post_scoped else "Advertisement Total Vacancies"
        return labels.get(relative_path, humanize(relative_path.replace(".", "_")))

    @staticmethod
    def _input_type(value_type: CandidateValueType, value: Any) -> str:
        if value_type == CandidateValueType.DATE:
            return "date"
        if value_type == CandidateValueType.INTEGER:
            return "number"
        if value_type == CandidateValueType.DECIMAL:
            return "decimal"
        if value_type == CandidateValueType.BOOLEAN:
            return "boolean"
        if value_type == CandidateValueType.JSON or (
            value_type == CandidateValueType.STRING and len(str(value)) > 160
        ):
            return "textarea"
        if value_type == CandidateValueType.NULL:
            return "readonly"
        return "text"

    @staticmethod
    def _form_value(value_type: CandidateValueType, value: Any) -> str:
        if value_type == CandidateValueType.JSON:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        if value_type == CandidateValueType.BOOLEAN:
            return "true" if value else "false"
        return "" if value is None else str(value)

    @staticmethod
    def _scope_outcome(items: list[Any]) -> str | None:
        if not items or any(item.status != ReviewItemStatus.RESOLVED for item in items):
            return None
        return ReviewCaseViewService._decision_outcome(
            [item.decision.decision for item in items if item.decision is not None]
        )

    @staticmethod
    def _scope_outcome_from_views(items: list[dict[str, Any]]) -> str | None:
        if not items or any(item["status"] != ReviewItemStatus.RESOLVED.value for item in items):
            return None
        return ReviewCaseViewService._decision_outcome(
            [ReviewDecisionType(item["decision"]["decision"]) for item in items]
        )

    @staticmethod
    def _decision_outcome(decisions: list[ReviewDecisionType]) -> str:
        if ReviewDecisionType.REQUEST_REVERIFICATION in decisions:
            return "REVERIFICATION_REQUESTED"
        if ReviewDecisionType.REJECT in decisions:
            return "REJECTED"
        if ReviewDecisionType.CORRECT_AND_APPROVE in decisions:
            return "APPROVED_WITH_CORRECTIONS"
        return "APPROVED"

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

    def _verification_view(self, field_verification: FieldVerification) -> dict[str, Any]:
        return {
            "id": field_verification.id,
            "outcome": (
                field_verification.outcome.value if field_verification.outcome is not None else None
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
            "corrected_value_raw": decision.corrected_value,
            "corrected_value_type": (
                decision.corrected_value_type.value
                if decision.corrected_value_type is not None
                else None
            ),
        }
