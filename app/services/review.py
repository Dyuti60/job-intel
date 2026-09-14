import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidates import AdvertisementSplitStatus
from app.models.confidence import (
    ConfidencePolicyVersion,
    FieldConfidenceAssessment,
    ReviewPriority,
    ReviewReasonCode,
    RevisionConfidenceAssessment,
)
from app.models.review import (
    ReviewCase,
    ReviewCaseOutcome,
    ReviewCaseStatus,
    ReviewDecision,
    ReviewDecisionType,
    ReviewItem,
    ReviewItemScope,
    ReviewItemStatus,
)
from app.repositories.candidates import CandidateRevisionRepository
from app.repositories.confidence import RevisionConfidenceRepository
from app.repositories.review import (
    ReviewCaseRepository,
    ReviewDecisionRepository,
    ReviewItemRepository,
)
from app.schemas.review import ReviewDecisionCreate
from app.services.candidate_values import normalize_typed_value
from app.services.confidence import ConfidenceService
from app.services.confidence_v2 import ConfidenceV2Service
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.review_routing import ReviewRoutingService

REVISION_ITEM_REASONS = {
    ReviewReasonCode.PARTIAL_VERIFICATION.value,
    ReviewReasonCode.REVISION_SCORE_BELOW_THRESHOLD.value,
}


class ReviewService:
    def __init__(self, session: Session, *, commit: bool = True) -> None:
        self.session = session
        self.commit = commit
        self.cases = ReviewCaseRepository(session)
        self.items = ReviewItemRepository(session)
        self.decisions = ReviewDecisionRepository(session)
        self.confidence = RevisionConfidenceRepository(session)
        self.revisions = CandidateRevisionRepository(session)

    def create_case(self, revision_confidence_assessment_id: uuid.UUID) -> tuple[ReviewCase, bool]:
        assessment = self.confidence.get(revision_confidence_assessment_id)
        if assessment is None:
            raise ResourceNotFoundError("Revision confidence assessment not found")
        if assessment.policy_version == ConfidencePolicyVersion.V2:
            return self._create_routing_case(assessment)
        if not assessment.review_required:
            raise DomainConflictError(
                "Revision confidence assessment does not require Human Review"
            )

        field_assessments = self._validate_confidence_integrity(assessment)
        existing = self.cases.get_by_confidence_assessment(assessment.id)
        if existing is not None:
            return self.get_case(existing.id), False

        now = datetime.now(UTC)
        review_case = ReviewCase(
            candidate_revision_id=assessment.candidate_revision_id,
            verification_run_id=assessment.verification_run_id,
            revision_confidence_assessment_id=assessment.id,
            status=ReviewCaseStatus.QUEUED,
            priority=assessment.review_priority,
            policy_version=assessment.policy_version,
            revision_score_snapshot=assessment.score,
            revision_review_reason_codes_snapshot=copy.deepcopy(assessment.review_reason_codes),
            component_breakdown_snapshot=copy.deepcopy(assessment.component_breakdown),
            opened_at=now,
        )
        self.cases.add(review_case)
        self.session.flush()

        item_count = 0
        for field_assessment in field_assessments:
            if not field_assessment.review_required:
                continue
            verification = field_assessment.field_verification
            self.items.add(
                ReviewItem(
                    review_case_id=review_case.id,
                    item_key=f"FIELD:{field_assessment.id}",
                    scope=ReviewItemScope.FIELD,
                    field_confidence_assessment_id=field_assessment.id,
                    candidate_field_id=verification.candidate_field_id,
                    status=ReviewItemStatus.PENDING,
                    priority=field_assessment.review_priority,
                    policy_version=field_assessment.policy_version,
                    field_path_snapshot=verification.candidate_field_path_snapshot,
                    candidate_value_type_snapshot=(verification.candidate_field_type_snapshot),
                    candidate_value_snapshot=copy.deepcopy(
                        verification.candidate_field_value_snapshot
                    ),
                    confidence_score_snapshot=field_assessment.score,
                    review_reason_codes_snapshot=copy.deepcopy(
                        field_assessment.review_reason_codes
                    ),
                    component_breakdown_snapshot=copy.deepcopy(
                        field_assessment.component_breakdown
                    ),
                )
            )
            item_count += 1

        revision_reasons = sorted(set(assessment.review_reason_codes) & REVISION_ITEM_REASONS)
        if revision_reasons:
            self.items.add(
                ReviewItem(
                    review_case_id=review_case.id,
                    item_key="REVISION",
                    scope=ReviewItemScope.REVISION,
                    status=ReviewItemStatus.PENDING,
                    priority=assessment.review_priority,
                    policy_version=assessment.policy_version,
                    confidence_score_snapshot=assessment.score,
                    review_reason_codes_snapshot=revision_reasons,
                    component_breakdown_snapshot=copy.deepcopy(assessment.component_breakdown),
                )
            )
            item_count += 1
        if item_count == 0:
            raise DomainConflictError(
                "Review-required confidence assessment produced no review items"
            )

        try:
            self._save()
        except IntegrityError as error:
            self.session.rollback()
            existing = self.cases.get_by_confidence_assessment(assessment.id)
            if existing is not None:
                return self.get_case(existing.id), False
            raise DomainConflictError(
                "Review case conflicted with concurrent queue generation; retry"
            ) from error
        return self.get_case(review_case.id), True

    def _create_routing_case(
        self, assessment: RevisionConfidenceAssessment
    ) -> tuple[ReviewCase, bool]:
        routing, _ = ReviewRoutingService(self.session, commit=False).assess(assessment.id)
        if not routing.review_required:
            raise DomainConflictError("Review-routing assessment does not require Human Review")
        field_assessments = ConfidenceV2Service(self.session, commit=False).get_revision_assessment(
            assessment.verification_run_id
        )[1]
        existing = self.cases.get_by_routing_assessment(routing.id)
        if existing is not None:
            return self.get_case(existing.id), False

        now = datetime.now(UTC)
        review_case = ReviewCase(
            candidate_revision_id=assessment.candidate_revision_id,
            verification_run_id=assessment.verification_run_id,
            revision_confidence_assessment_id=assessment.id,
            review_routing_assessment_id=routing.id,
            status=ReviewCaseStatus.QUEUED,
            priority=routing.priority,
            policy_version=assessment.policy_version,
            revision_score_snapshot=assessment.score,
            revision_review_reason_codes_snapshot=copy.deepcopy(routing.reason_codes),
            component_breakdown_snapshot=copy.deepcopy(routing.component_breakdown),
            opened_at=now,
        )
        self.cases.add(review_case)
        self.session.flush()
        confidence_by_id = {str(item.id): item for item in field_assessments}
        covered_reasons: set[str] = set()
        for route in routing.field_routes:
            field_assessment = confidence_by_id.get(route["field_confidence_assessment_id"])
            if field_assessment is None:
                raise DomainConflictError("Routing references an unavailable field confidence")
            verification = field_assessment.field_verification
            reasons = list(route["reason_codes"])
            covered_reasons.update(reasons)
            self.items.add(
                ReviewItem(
                    review_case_id=review_case.id,
                    item_key=f"FIELD:{field_assessment.id}",
                    scope=ReviewItemScope.FIELD,
                    field_confidence_assessment_id=field_assessment.id,
                    candidate_field_id=verification.candidate_field_id,
                    status=ReviewItemStatus.PENDING,
                    priority=ReviewPriority(route["priority"]),
                    policy_version=assessment.policy_version,
                    field_path_snapshot=verification.candidate_field_path_snapshot,
                    candidate_value_type_snapshot=verification.candidate_field_type_snapshot,
                    candidate_value_snapshot=copy.deepcopy(
                        verification.candidate_field_value_snapshot
                    ),
                    confidence_score_snapshot=field_assessment.score,
                    review_reason_codes_snapshot=reasons,
                    component_breakdown_snapshot={
                        "confidence": copy.deepcopy(field_assessment.component_breakdown),
                        "routing": copy.deepcopy(route),
                    },
                )
            )
        revision_reasons = [
            reason for reason in routing.reason_codes if reason not in covered_reasons
        ]
        if revision_reasons:
            self.items.add(
                ReviewItem(
                    review_case_id=review_case.id,
                    item_key="REVISION",
                    scope=ReviewItemScope.REVISION,
                    status=ReviewItemStatus.PENDING,
                    priority=routing.priority,
                    policy_version=assessment.policy_version,
                    confidence_score_snapshot=assessment.score,
                    review_reason_codes_snapshot=revision_reasons,
                    component_breakdown_snapshot=copy.deepcopy(routing.component_breakdown),
                )
            )
        if not routing.field_routes and not revision_reasons:
            raise DomainConflictError("Review routing produced no review items")
        try:
            self._save()
        except IntegrityError as error:
            self.session.rollback()
            existing = self.cases.get_by_routing_assessment(routing.id)
            if existing is not None:
                return self.get_case(existing.id), False
            raise DomainConflictError(
                "Review case conflicted with concurrent routing; retry"
            ) from error
        return self.get_case(review_case.id), True

    def get_case(self, case_id: uuid.UUID) -> ReviewCase:
        review_case = self.cases.get(case_id)
        if review_case is None:
            raise ResourceNotFoundError("Review case not found")
        return review_case

    def list_cases(
        self,
        *,
        status: ReviewCaseStatus | None,
        priority: ReviewPriority | None,
        candidate_revision_id: uuid.UUID | None,
        verification_run_id: uuid.UUID | None,
        offset: int,
        limit: int,
    ) -> list[ReviewCase]:
        return self.cases.list(
            status=status,
            priority=priority,
            candidate_revision_id=candidate_revision_id,
            verification_run_id=verification_run_id,
            offset=offset,
            limit=limit,
        )

    def start_case(self, case_id: uuid.UUID) -> ReviewCase:
        review_case = self.get_case(case_id)
        if review_case.status != ReviewCaseStatus.QUEUED:
            raise DomainConflictError(
                f"Cannot start review case in {review_case.status.value} status"
            )
        review_case.status = ReviewCaseStatus.IN_REVIEW
        review_case.started_at = datetime.now(UTC)
        self._save()
        return self.get_case(review_case.id)

    def cancel_case(self, case_id: uuid.UUID) -> tuple[ReviewCase, bool]:
        review_case = self.get_case(case_id)
        if review_case.status == ReviewCaseStatus.CANCELLED:
            return review_case, False
        if review_case.status == ReviewCaseStatus.RESOLVED:
            raise DomainConflictError("Resolved review case is immutable")
        review_case.status = ReviewCaseStatus.CANCELLED
        review_case.resolved_at = datetime.now(UTC)
        self._save()
        return self.get_case(review_case.id), True

    def resolve_case(self, case_id: uuid.UUID) -> tuple[ReviewCase, bool]:
        review_case = self.get_case(case_id)
        if review_case.status == ReviewCaseStatus.RESOLVED:
            return review_case, False
        if review_case.status != ReviewCaseStatus.IN_REVIEW:
            raise DomainConflictError(
                f"Cannot resolve review case in {review_case.status.value} status"
            )
        if self.items.pending_count(review_case.id):
            raise DomainConflictError("Review case still has pending items")
        self._resolve_case(review_case, datetime.now(UTC))
        self._save()
        return self.get_case(review_case.id), True

    def get_item(self, item_id: uuid.UUID) -> ReviewItem:
        item = self.items.get(item_id)
        if item is None:
            raise ResourceNotFoundError("Review item not found")
        return item

    def decide_item(
        self, item_id: uuid.UUID, data: ReviewDecisionCreate
    ) -> tuple[ReviewDecision, bool]:
        item = self.get_item(item_id)
        normalized_value = self._validate_decision(item, data)
        existing = self.decisions.get_for_item(item.id)
        if existing is not None:
            if self._decision_matches(existing, data, normalized_value):
                return existing, False
            raise DomainConflictError("Review item already has a different final decision")

        review_case = item.review_case
        if review_case.status != ReviewCaseStatus.IN_REVIEW:
            raise DomainConflictError(
                f"Review decisions require an IN_REVIEW case, not {review_case.status.value}"
            )
        if item.status != ReviewItemStatus.PENDING:
            raise DomainConflictError("Resolved review item is immutable")

        now = datetime.now(UTC)
        decision = ReviewDecision(
            review_item_id=item.id,
            decision=data.decision,
            reviewer_identifier=data.reviewer_identifier,
            decision_note=data.decision_note,
            original_value_snapshot=copy.deepcopy(item.candidate_value_snapshot),
            original_value_type_snapshot=item.candidate_value_type_snapshot,
            corrected_value_type=data.corrected_value_type,
            corrected_value=copy.deepcopy(normalized_value),
            evidence_note=data.evidence_note,
            decided_at=now,
        )
        self.decisions.add(decision)
        item.status = ReviewItemStatus.RESOLVED
        item.resolved_at = now
        self.session.flush()
        if self.items.pending_count(review_case.id) == 0:
            self._resolve_case(review_case, now)
        try:
            self._save()
        except IntegrityError as error:
            self.session.rollback()
            existing = self.decisions.get_for_item(item.id)
            if existing is not None and self._decision_matches(existing, data, normalized_value):
                return existing, False
            raise DomainConflictError(
                "Review decision conflicted with concurrent submission; retry"
            ) from error
        return decision, True

    def submit_review_scope(
        self,
        case_id: uuid.UUID,
        *,
        post_key: str | None,
        item_decisions: dict[uuid.UUID, ReviewDecisionType],
        reviewer_identifier: str,
        decision_note: str,
        approve: bool,
    ) -> ReviewCase:
        """Apply one complete Post/legacy review form in a single transaction."""
        review_case = self.get_case(case_id)
        if review_case.status != ReviewCaseStatus.IN_REVIEW:
            raise DomainConflictError(
                f"Review decisions require an IN_REVIEW case, not {review_case.status.value}"
            )
        note = decision_note.strip()
        if not note:
            raise DomainConflictError("A reviewer comment is required")

        revision = self.revisions.get(review_case.candidate_revision_id)
        if revision is None:
            raise DomainConflictError("Review case candidate revision is unavailable")
        advertisement = revision.advertisement_revision
        explicit_posts = (
            advertisement.posts
            if advertisement is not None
            and advertisement.split_status == AdvertisementSplitStatus.EXPLICIT
            else []
        )
        explicit_post_keys = {post.post_key for post in explicit_posts}
        if explicit_posts and post_key not in explicit_post_keys:
            raise DomainConflictError("A valid focused Post is required")
        if not explicit_posts and post_key is not None:
            raise DomainConflictError("This review is Advertisement-level")

        relevant_items = [
            item
            for item in review_case.items
            if post_key is None
            or self._post_key(item.field_path_snapshot) in {None, post_key}
        ]
        pending_items = [item for item in relevant_items if item.status == ReviewItemStatus.PENDING]
        pending_ids = {item.id for item in pending_items}
        if set(item_decisions) != pending_ids:
            raise DomainConflictError("Choose Approve or Reject for every pending review item")
        if any(
            decision not in {ReviewDecisionType.APPROVE_AS_IS, ReviewDecisionType.REJECT}
            for decision in item_decisions.values()
        ):
            raise DomainConflictError("Post review supports only Approve or Reject")

        decisions_by_item = {
            item.id: (
                item.decision.decision if item.decision is not None else item_decisions.get(item.id)
            )
            for item in relevant_items
        }
        if post_key is not None:
            shared_rejections = any(
                self._post_key(item.field_path_snapshot) is None
                and decisions_by_item[item.id] == ReviewDecisionType.REJECT
                for item in relevant_items
            )
            if shared_rejections:
                raise DomainConflictError(
                    "A shared Advertisement item cannot reject only one Post"
                )
            post_rejected = any(
                self._post_key(item.field_path_snapshot) == post_key
                and decisions_by_item[item.id] == ReviewDecisionType.REJECT
                for item in relevant_items
            )
        else:
            post_rejected = ReviewDecisionType.REJECT in decisions_by_item.values()

        any_rejected = ReviewDecisionType.REJECT in decisions_by_item.values()
        if approve and any_rejected:
            raise DomainConflictError("Final Approve requires every item to be approved")
        if not approve and not post_rejected:
            raise DomainConflictError("Final Reject requires rejecting a focused Post item")

        worker = ReviewService(self.session, commit=False)
        for item in pending_items:
            worker.decide_item(
                item.id,
                ReviewDecisionCreate(
                    decision=item_decisions[item.id],
                    reviewer_identifier=reviewer_identifier,
                    decision_note=note,
                ),
            )
        self._save()
        return self.get_case(case_id)

    def approved_projection(self, case_id: uuid.UUID) -> dict[str, Any]:
        review_case = self.get_case(case_id)
        if review_case.status != ReviewCaseStatus.RESOLVED:
            raise DomainConflictError("Approved projection requires a resolved review case")
        revision = self.revisions.get(review_case.candidate_revision_id)
        if revision is None:
            raise DomainConflictError("Review case candidate revision is unavailable")
        if review_case.review_routing_assessment_id is not None:
            return self._routing_approved_projection(review_case, revision)

        master_eligible = review_case.outcome in {
            ReviewCaseOutcome.APPROVED,
            ReviewCaseOutcome.APPROVED_WITH_CORRECTIONS,
        }
        items_by_field = {
            item.candidate_field_id: item
            for item in review_case.items
            if item.scope == ReviewItemScope.FIELD
        }
        fields = []
        for field in revision.fields:
            item = items_by_field.get(field.id)
            decision = item.decision if item is not None else None
            corrected = bool(
                decision is not None and decision.decision == ReviewDecisionType.CORRECT_AND_APPROVE
            )
            effective_value = None
            if master_eligible:
                effective_value = copy.deepcopy(
                    decision.corrected_value if corrected else field.value
                )
            fields.append(
                {
                    "candidate_field_id": field.id,
                    "field_path": field.field_path,
                    "value_type": field.value_type,
                    "original_value": copy.deepcopy(field.value),
                    "effective_value": effective_value,
                    "approved": master_eligible,
                    "corrected": corrected,
                    "review_decision_id": decision.id if decision is not None else None,
                }
            )
        return {
            "review_case_id": review_case.id,
            "candidate_revision_id": review_case.candidate_revision_id,
            "outcome": review_case.outcome,
            "master_eligible": master_eligible,
            "fields": fields,
        }

    @staticmethod
    def _routing_approved_projection(review_case: ReviewCase, revision) -> dict[str, Any]:
        decisions_by_field = {
            item.candidate_field_id: item.decision
            for item in review_case.items
            if item.scope == ReviewItemScope.FIELD
        }
        blocked_posts: set[str] = set()
        global_block = False
        for item in review_case.items:
            decision = item.decision
            if decision is None or decision.decision not in {
                ReviewDecisionType.REJECT,
                ReviewDecisionType.REQUEST_REVERIFICATION,
            }:
                continue
            post_key = ReviewService._post_key(item.field_path_snapshot)
            if item.scope == ReviewItemScope.REVISION or post_key is None:
                global_block = True
            else:
                blocked_posts.add(post_key)

        fields = []
        approved_post_keys: set[str] = set()
        for field in revision.fields:
            post_key = ReviewService._post_key(field.field_path)
            approved = not global_block and (post_key is None or post_key not in blocked_posts)
            decision = decisions_by_field.get(field.id)
            corrected = bool(
                approved
                and decision is not None
                and decision.decision == ReviewDecisionType.CORRECT_AND_APPROVE
            )
            if approved and post_key is not None:
                approved_post_keys.add(post_key)
            fields.append(
                {
                    "candidate_field_id": field.id,
                    "field_path": field.field_path,
                    "value_type": field.value_type,
                    "original_value": copy.deepcopy(field.value),
                    "effective_value": (
                        copy.deepcopy(decision.corrected_value if corrected else field.value)
                        if approved
                        else None
                    ),
                    "approved": approved,
                    "corrected": corrected,
                    "review_decision_id": decision.id if decision is not None else None,
                }
            )
        explicit_posts = (
            revision.advertisement_revision.posts
            if revision.advertisement_revision is not None
            else []
        )
        master_eligible = not global_block and (
            bool(approved_post_keys) if explicit_posts else any(item["approved"] for item in fields)
        )
        return {
            "review_case_id": review_case.id,
            "candidate_revision_id": review_case.candidate_revision_id,
            "outcome": review_case.outcome,
            "master_eligible": master_eligible,
            "approved_post_keys": sorted(approved_post_keys),
            "blocked_post_keys": sorted(blocked_posts),
            "fields": fields,
        }

    @staticmethod
    def _post_key(field_path: str | None) -> str | None:
        if field_path is None or not field_path.startswith("posts."):
            return None
        parts = field_path.split(".", 2)
        return parts[1] if len(parts) == 3 else None

    def _validate_confidence_integrity(
        self, assessment: RevisionConfidenceAssessment
    ) -> list[FieldConfidenceAssessment]:
        if assessment.policy_version == ConfidencePolicyVersion.V2:
            validated, fields, _ = ConfidenceV2Service(self.session, commit=self.commit).score_run(
                assessment.verification_run_id
            )
            if validated.id != assessment.id:
                raise DomainConflictError("Confidence V2 identity mismatch")
            return fields
        return ConfidenceService.validate_persisted_revision_assessment(
            self.session, assessment, commit=self.commit
        )

    def _save(self) -> None:
        self.session.commit() if self.commit else self.session.flush()

    @staticmethod
    def _validate_decision(item: ReviewItem, data: ReviewDecisionCreate) -> Any:
        if (
            item.scope == ReviewItemScope.REVISION
            and data.decision == ReviewDecisionType.CORRECT_AND_APPROVE
        ):
            raise DomainConflictError("CORRECT_AND_APPROVE is allowed only for FIELD review items")
        if data.decision != ReviewDecisionType.CORRECT_AND_APPROVE:
            return None
        original_type = item.candidate_value_type_snapshot
        if original_type is None or data.corrected_value_type != original_type:
            raise DomainConflictError(
                "Corrected value type must match the original CandidateField type"
            )
        try:
            normalized = normalize_typed_value(original_type, data.corrected_value)
        except ValueError as error:
            raise DomainConflictError(str(error)) from error
        if normalized == item.candidate_value_snapshot:
            raise DomainConflictError(
                "Corrected value must differ; use APPROVE_AS_IS for an unchanged value"
            )
        return normalized

    @staticmethod
    def _decision_matches(
        existing: ReviewDecision,
        data: ReviewDecisionCreate,
        normalized_value: Any,
    ) -> bool:
        return (
            existing.decision == data.decision
            and existing.reviewer_identifier == data.reviewer_identifier
            and existing.decision_note == data.decision_note
            and existing.corrected_value_type == data.corrected_value_type
            and existing.corrected_value == normalized_value
            and existing.evidence_note == data.evidence_note
        )

    def _resolve_case(self, review_case: ReviewCase, resolved_at: datetime) -> None:
        decisions = self.decisions.list_for_case(review_case.id)
        if len(decisions) != len(review_case.items):
            raise DomainConflictError("Review case decision history is incomplete")
        decision_types = {item.decision for item in decisions}
        if ReviewDecisionType.REQUEST_REVERIFICATION in decision_types:
            outcome = ReviewCaseOutcome.REVERIFICATION_REQUESTED
        elif ReviewDecisionType.REJECT in decision_types:
            outcome = ReviewCaseOutcome.REJECTED
        elif ReviewDecisionType.CORRECT_AND_APPROVE in decision_types:
            outcome = ReviewCaseOutcome.APPROVED_WITH_CORRECTIONS
        else:
            outcome = ReviewCaseOutcome.APPROVED
        review_case.status = ReviewCaseStatus.RESOLVED
        review_case.outcome = outcome
        review_case.resolved_at = resolved_at
