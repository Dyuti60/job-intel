import copy
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidates import CandidateStatus, CandidateValueType
from app.models.confidence import (
    ConfidencePolicyVersion,
    FieldConfidenceAssessment,
    RevisionConfidenceAssessment,
)
from app.models.master import (
    MasterChange,
    MasterChangeType,
    MasterField,
    MasterFieldValueOrigin,
    MasterPost,
    MasterPostFact,
    MasterPublicationEvent,
    PublicationPath,
    PublicationResult,
    RecruitmentMaster,
    RecruitmentMasterRevision,
    RecruitmentMasterStatus,
)
from app.models.review import (
    ReviewCase,
    ReviewCaseOutcome,
    ReviewCaseStatus,
    ReviewDecisionType,
    ReviewItemScope,
)
from app.models.verification import FieldVerificationStatus, VerificationRunStatus
from app.repositories.candidates import CandidateRevisionRepository
from app.repositories.confidence import RevisionConfidenceRepository
from app.repositories.master import (
    MasterChangeRepository,
    MasterPublicationEventRepository,
    MasterRevisionRepository,
    RecruitmentMasterRepository,
)
from app.repositories.review import ReviewCaseRepository
from app.repositories.verification import FieldVerificationRepository, VerificationRunRepository
from app.services.candidate_values import compute_persisted_revision_hash, normalize_typed_value
from app.services.confidence import ConfidenceService
from app.services.confidence_v2 import ConfidenceV2Service
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.review import ReviewService
from app.services.review_routing import ReviewRoutingService


@dataclass(frozen=True)
class MasterPublicationPreview:
    publication_path: PublicationPath
    projection_hash: str
    master_exists: bool
    matching_revision_exists: bool
    already_processed: bool


def compute_projection_hash(
    *,
    authority_code: str,
    candidate_key: str,
    display_name: str,
    fields: list[tuple[str, CandidateValueType, Any]],
) -> str:
    payload = {
        "authority_code": authority_code,
        "candidate_key": candidate_key,
        "display_name": display_name,
        "fields": [
            {"field_path": path, "value_type": value_type.value, "value": value}
            for path, value_type, value in sorted(fields, key=lambda item: item[0])
        ],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


class MasterPublisherService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.masters = RecruitmentMasterRepository(session)
        self.master_revisions = MasterRevisionRepository(session)
        self.events = MasterPublicationEventRepository(session)
        self.changes = MasterChangeRepository(session)
        self.candidate_revisions = CandidateRevisionRepository(session)
        self.confidence = RevisionConfidenceRepository(session)
        self.runs = VerificationRunRepository(session)
        self.field_verifications = FieldVerificationRepository(session)
        self.review_cases = ReviewCaseRepository(session)

    def publish(
        self, revision_confidence_assessment_id: uuid.UUID
    ) -> tuple[RecruitmentMaster, RecruitmentMasterRevision, MasterPublicationEvent, bool]:
        assessment = self.confidence.get(revision_confidence_assessment_id)
        if assessment is None:
            raise ResourceNotFoundError("Revision confidence assessment not found")
        revision, run, field_assessments = self._validate_verification(assessment)
        candidate = revision.recruitment_candidate
        effective_fields, publication_path, review_case = self._effective_projection(
            assessment, revision, field_assessments
        )
        projection_hash = compute_projection_hash(
            authority_code=candidate.recruiting_authority.code,
            candidate_key=candidate.candidate_key,
            display_name=candidate.display_name,
            fields=[
                (item["field_path"], item["value_type"], item["value"]) for item in effective_fields
            ],
        )

        existing_event = self.events.get_by_confidence_assessment(assessment.id)
        if existing_event is not None:
            master_revision = self.master_revisions.get(existing_event.master_revision_id)
            master = self.masters.get(existing_event.recruitment_master_id)
            if master is None or master_revision is None:
                raise DomainConflictError("Publication event provenance is unavailable")
            if (
                master_revision.projection_hash != projection_hash
                or existing_event.source_candidate_revision_id != revision.id
                or existing_event.verification_run_id != run.id
                or existing_event.publication_path != publication_path
                or existing_event.review_case_id
                != (review_case.id if review_case is not None else None)
            ):
                raise DomainConflictError("Persisted publication event fails integrity validation")
            return master, master_revision, existing_event, False

        now = datetime.now(UTC)
        verified_at = run.completed_at
        if verified_at is None:
            raise DomainConflictError("Completed VerificationRun has no completion timestamp")
        try:
            master = self.masters.get_by_identity(
                candidate.recruiting_authority_id, candidate.candidate_key
            )
            if master is None:
                master = RecruitmentMaster(
                    recruiting_authority_id=candidate.recruiting_authority_id,
                    candidate_key=candidate.candidate_key,
                    display_name=candidate.display_name,
                    status=RecruitmentMasterStatus.ACTIVE,
                    first_published_at=now,
                    last_published_at=now,
                    last_verified_at=verified_at,
                )
                self.masters.add(master)
                self.session.flush()

            previous_revision = master.current_revision
            master_revision = self.master_revisions.get_by_hash(master.id, projection_hash)
            revision_created = master_revision is None
            if revision_created:
                master_revision = RecruitmentMasterRevision(
                    recruitment_master_id=master.id,
                    revision_number=self.master_revisions.next_revision_number(master.id),
                    projection_hash=projection_hash,
                    display_name=candidate.display_name,
                    source_candidate_revision_id=revision.id,
                    verification_run_id=run.id,
                    revision_confidence_assessment_id=assessment.id,
                    review_case_id=review_case.id if review_case is not None else None,
                    publication_path=publication_path,
                    published_at=now,
                    verified_at=verified_at,
                )
                self.master_revisions.add(master_revision)
                self.session.flush()
                master_fields = []
                for item in effective_fields:
                    master_field = MasterField(
                        master_revision_id=master_revision.id,
                        field_path=item["field_path"],
                        value_type=item["value_type"],
                        value=copy.deepcopy(item["value"]),
                        source_candidate_field_id=item["source_candidate_field_id"],
                        review_decision_id=item["review_decision_id"],
                        value_origin=item["value_origin"],
                    )
                    self.session.add(master_field)
                    master_fields.append(master_field)
                self.session.flush()
                self._persist_master_posts(revision, master_revision, master_fields)
                self._record_changes(master, previous_revision, master_revision)
                master.display_name = candidate.display_name
                master.current_revision_id = master_revision.id
                master.last_published_at = now
            elif master.current_revision_id != master_revision.id:
                master.display_name = master_revision.display_name
                master.current_revision_id = master_revision.id

            if self._timestamp_key(verified_at) > self._timestamp_key(master.last_verified_at):
                master.last_verified_at = verified_at
            event = MasterPublicationEvent(
                recruitment_master_id=master.id,
                master_revision_id=master_revision.id,
                source_candidate_revision_id=revision.id,
                verification_run_id=run.id,
                revision_confidence_assessment_id=assessment.id,
                review_case_id=review_case.id if review_case is not None else None,
                publication_path=publication_path,
                result=(
                    PublicationResult.CREATED if revision_created else PublicationResult.UNCHANGED
                ),
                published_or_verified_at=now,
            )
            self.events.add(event)
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            replay = self.events.get_by_confidence_assessment(assessment.id)
            if replay is not None:
                master = self.masters.get(replay.recruitment_master_id)
                master_revision = self.master_revisions.get(replay.master_revision_id)
                if master is not None and master_revision is not None:
                    return master, master_revision, replay, False
            raise DomainConflictError(
                "Publication conflicted with concurrent publishing; retry"
            ) from error
        except Exception:
            self.session.rollback()
            raise
        return (
            self.get_master(master.id),
            self.get_revision(master_revision.id),
            event,
            revision_created,
        )

    def preview(self, revision_confidence_assessment_id: uuid.UUID) -> MasterPublicationPreview:
        """Validate and classify a publication without changing Master persistence."""
        assessment = self.confidence.get(revision_confidence_assessment_id)
        if assessment is None:
            raise ResourceNotFoundError("Revision confidence assessment not found")
        revision, _, field_assessments = self._validate_verification(assessment)
        candidate = revision.recruitment_candidate
        effective_fields, publication_path, _ = self._effective_projection(
            assessment, revision, field_assessments
        )
        projection_hash = compute_projection_hash(
            authority_code=candidate.recruiting_authority.code,
            candidate_key=candidate.candidate_key,
            display_name=candidate.display_name,
            fields=[
                (item["field_path"], item["value_type"], item["value"]) for item in effective_fields
            ],
        )
        master = self.masters.get_by_identity(
            candidate.recruiting_authority_id, candidate.candidate_key
        )
        return MasterPublicationPreview(
            publication_path=publication_path,
            projection_hash=projection_hash,
            master_exists=master is not None,
            matching_revision_exists=(
                master is not None
                and self.master_revisions.get_by_hash(master.id, projection_hash) is not None
            ),
            already_processed=(self.events.get_by_confidence_assessment(assessment.id) is not None),
        )

    def get_master(self, master_id: uuid.UUID) -> RecruitmentMaster:
        master = self.masters.get(master_id)
        if master is None:
            raise ResourceNotFoundError("Recruitment Master not found")
        return master

    def list_masters(
        self,
        *,
        recruiting_authority_id: uuid.UUID | None,
        status: RecruitmentMasterStatus | None,
        candidate_key: str | None,
        offset: int,
        limit: int,
    ) -> list[RecruitmentMaster]:
        return self.masters.list(
            recruiting_authority_id=recruiting_authority_id,
            status=status,
            candidate_key=candidate_key.strip().upper() if candidate_key else None,
            offset=offset,
            limit=limit,
        )

    def get_revision(self, revision_id: uuid.UUID) -> RecruitmentMasterRevision:
        revision = self.master_revisions.get(revision_id)
        if revision is None:
            raise ResourceNotFoundError("Recruitment Master revision not found")
        return revision

    def list_revisions(self, master_id: uuid.UUID) -> list[RecruitmentMasterRevision]:
        self.get_master(master_id)
        return self.master_revisions.list_for_master(master_id)

    def list_changes(self, master_id: uuid.UUID) -> list[MasterChange]:
        self.get_master(master_id)
        return self.changes.list_for_master(master_id)

    def list_events(self, master_id: uuid.UUID) -> list[MasterPublicationEvent]:
        self.get_master(master_id)
        return self.events.list_for_master(master_id)

    def _persist_master_posts(self, revision, master_revision, master_fields) -> None:
        interpretation = revision.advertisement_revision
        if interpretation is None or not interpretation.posts:
            return
        fields_by_source = {item.source_candidate_field_id: item for item in master_fields}
        for post in interpretation.posts:
            approved_facts = [
                fact for fact in post.facts if fact.candidate_field_id in fields_by_source
            ]
            if not approved_facts:
                continue
            master_post = MasterPost(
                master_revision_id=master_revision.id,
                source_recruitment_post_id=post.id,
                public_id=uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    "assam-job-intelligence:master-post:"
                    f"{master_revision.recruitment_master_id}:{post.post_key}",
                ),
                post_key=post.post_key,
                ordinal=post.ordinal,
                name=post.name,
                normalized_name=post.normalized_name,
            )
            self.session.add(master_post)
            self.session.flush()
            for fact in approved_facts:
                self.session.add(
                    MasterPostFact(
                        master_post_id=master_post.id,
                        master_revision_id=master_revision.id,
                        master_field_id=fields_by_source[fact.candidate_field_id].id,
                        source_post_fact_id=fact.id,
                        fact_key=fact.fact_key,
                    )
                )
        self.session.flush()

    def _validate_verification(
        self, assessment: RevisionConfidenceAssessment
    ) -> tuple[Any, Any, list[FieldConfidenceAssessment]]:
        revision = self.candidate_revisions.get(assessment.candidate_revision_id)
        if revision is None:
            raise DomainConflictError("Confidence CandidateRevision is unavailable")
        candidate = revision.recruitment_candidate
        if candidate.status != CandidateStatus.READY_FOR_VERIFICATION:
            raise DomainConflictError("Candidate is not READY_FOR_VERIFICATION")
        run = self.runs.get(assessment.verification_run_id)
        if run is None:
            raise DomainConflictError("Confidence VerificationRun is unavailable")
        if (
            run.candidate_revision_id != revision.id
            or assessment.candidate_revision_id != revision.id
        ):
            raise DomainConflictError("Confidence, run, and candidate revision do not match")
        if run.status != VerificationRunStatus.COMPLETED:
            raise DomainConflictError("Publishing requires a COMPLETED VerificationRun")

        expected_revision_hash = compute_persisted_revision_hash(revision)
        if revision.revision_hash != expected_revision_hash:
            raise DomainConflictError("CandidateRevision hash fails integrity validation")
        if run.candidate_revision_hash_snapshot != revision.revision_hash:
            raise DomainConflictError("VerificationRun revision hash snapshot mismatch")

        if assessment.policy_version == ConfidencePolicyVersion.V2:
            validated, field_assessments, _ = ConfidenceV2Service(
                self.session, commit=False
            ).score_run(run.id)
            if validated.id != assessment.id:
                raise DomainConflictError("Confidence V2 identity mismatch")
        else:
            field_assessments = ConfidenceService.validate_persisted_revision_assessment(
                self.session, assessment
            )
        verifications = self.field_verifications.list_for_run(run.id)
        revision_field_ids = {field.id for field in revision.fields}
        verification_field_ids = {item.candidate_field_id for item in verifications}
        if (
            run.fields_total != len(revision.fields)
            or len(verifications) != len(revision.fields)
            or revision_field_ids != verification_field_ids
            or any(item.status != FieldVerificationStatus.FINALIZED for item in verifications)
            or len(field_assessments) != len(revision.fields)
        ):
            raise DomainConflictError("Verification/confidence coverage is incomplete")
        fields_by_id = {field.id: field for field in revision.fields}
        for verification in verifications:
            field = fields_by_id[verification.candidate_field_id]
            if (
                verification.candidate_field_path_snapshot != field.field_path
                or verification.candidate_field_type_snapshot != field.value_type
                or verification.candidate_field_value_snapshot != field.value
            ):
                raise DomainConflictError("FieldVerification candidate snapshot mismatch")
        return revision, run, field_assessments

    def _effective_projection(
        self,
        assessment: RevisionConfidenceAssessment,
        revision: Any,
        field_assessments: list[FieldConfidenceAssessment],
    ) -> tuple[list[dict[str, Any]], PublicationPath, ReviewCase | None]:
        if assessment.policy_version == ConfidencePolicyVersion.V2:
            return self._effective_routing_projection(assessment, revision)
        if not assessment.review_required:
            return (
                [
                    self._effective_field(
                        field.field_path,
                        field.value_type,
                        field.value,
                        field.id,
                        None,
                        MasterFieldValueOrigin.CANDIDATE_VERIFIED,
                    )
                    for field in revision.fields
                ],
                PublicationPath.VERIFIED_NO_REVIEW,
                None,
            )

        case_row = self.review_cases.get_by_confidence_assessment(assessment.id)
        if case_row is None:
            raise DomainConflictError("Required ReviewCase is missing")
        review_case = ReviewService(self.session).get_case(case_row.id)
        self._validate_review_integrity(review_case, assessment, field_assessments)
        if review_case.status != ReviewCaseStatus.RESOLVED:
            raise DomainConflictError("Required ReviewCase is not resolved")
        if review_case.outcome not in {
            ReviewCaseOutcome.APPROVED,
            ReviewCaseOutcome.APPROVED_WITH_CORRECTIONS,
        }:
            raise DomainConflictError(
                f"Review outcome {review_case.outcome.value} is not publishable"
            )
        projection = ReviewService(self.session).approved_projection(review_case.id)
        if not projection["master_eligible"]:
            raise DomainConflictError("Approved projection is not master-eligible")

        items_by_field = {
            item.candidate_field_id: item
            for item in review_case.items
            if item.scope == ReviewItemScope.FIELD
        }
        effective_fields = []
        for projected in projection["fields"]:
            item = items_by_field.get(projected["candidate_field_id"])
            decision = item.decision if item is not None else None
            if projected["corrected"]:
                origin = MasterFieldValueOrigin.HUMAN_CORRECTED
            elif decision is not None:
                origin = MasterFieldValueOrigin.HUMAN_APPROVED_AS_IS
            else:
                origin = MasterFieldValueOrigin.CANDIDATE_VERIFIED
            effective_fields.append(
                self._effective_field(
                    projected["field_path"],
                    projected["value_type"],
                    projected["effective_value"],
                    projected["candidate_field_id"],
                    decision.id if decision is not None else None,
                    origin,
                )
            )
        path = (
            PublicationPath.HUMAN_CORRECTED
            if review_case.outcome == ReviewCaseOutcome.APPROVED_WITH_CORRECTIONS
            else PublicationPath.HUMAN_APPROVED
        )
        return effective_fields, path, review_case

    def _effective_routing_projection(
        self, assessment: RevisionConfidenceAssessment, revision: Any
    ) -> tuple[list[dict[str, Any]], PublicationPath, ReviewCase | None]:
        routing, _ = ReviewRoutingService(self.session, commit=False).assess(assessment.id)
        if not routing.review_required:
            return (
                [
                    self._effective_field(
                        field.field_path,
                        field.value_type,
                        field.value,
                        field.id,
                        None,
                        MasterFieldValueOrigin.CANDIDATE_VERIFIED,
                    )
                    for field in revision.fields
                ],
                PublicationPath.VERIFIED_NO_REVIEW,
                None,
            )
        case_row = self.review_cases.get_by_routing_assessment(routing.id)
        if case_row is None:
            raise DomainConflictError("Required routing-driven ReviewCase is missing")
        review_case = ReviewService(self.session).get_case(case_row.id)
        if review_case.status != ReviewCaseStatus.RESOLVED:
            raise DomainConflictError("Required routing-driven ReviewCase is not resolved")
        if (
            review_case.candidate_revision_id != assessment.candidate_revision_id
            or review_case.verification_run_id != assessment.verification_run_id
            or review_case.review_routing_assessment_id != routing.id
            or review_case.revision_confidence_assessment_id != assessment.id
            or review_case.policy_version != assessment.policy_version
            or review_case.revision_score_snapshot != assessment.score
            or review_case.revision_review_reason_codes_snapshot != routing.reason_codes
            or review_case.priority != routing.priority
            or review_case.component_breakdown_snapshot != routing.component_breakdown
        ):
            raise DomainConflictError(
                "Routing-driven ReviewCase snapshot fails integrity validation"
            )
        field_confidences = ConfidenceV2Service(self.session, commit=False).get_revision_assessment(
            assessment.verification_run_id
        )[1]
        self._validate_routing_review_items(
            review_case, routing.field_routes, routing.reason_codes, field_confidences
        )
        projection = ReviewService(self.session).approved_projection(review_case.id)
        if not projection["master_eligible"]:
            raise DomainConflictError("Routing review has no publishable Advertisement or Post")
        items_by_field = {
            item.candidate_field_id: item
            for item in review_case.items
            if item.scope == ReviewItemScope.FIELD
        }
        effective_fields = []
        any_correction = False
        for projected in projection["fields"]:
            if not projected["approved"]:
                continue
            item = items_by_field.get(projected["candidate_field_id"])
            decision = item.decision if item is not None else None
            if projected["corrected"]:
                origin = MasterFieldValueOrigin.HUMAN_CORRECTED
                any_correction = True
            elif decision is not None:
                origin = MasterFieldValueOrigin.HUMAN_APPROVED_AS_IS
            else:
                origin = MasterFieldValueOrigin.CANDIDATE_VERIFIED
            effective_fields.append(
                self._effective_field(
                    projected["field_path"],
                    projected["value_type"],
                    projected["effective_value"],
                    projected["candidate_field_id"],
                    decision.id if decision is not None else None,
                    origin,
                )
            )
        return (
            effective_fields,
            (PublicationPath.HUMAN_CORRECTED if any_correction else PublicationPath.HUMAN_APPROVED),
            review_case,
        )

    @staticmethod
    def _validate_routing_review_items(
        review_case: ReviewCase,
        field_routes: list[dict[str, Any]],
        routing_reasons: list[str],
        field_confidences: list[FieldConfidenceAssessment],
    ) -> None:
        routes_by_confidence = {
            route["field_confidence_assessment_id"]: route for route in field_routes
        }
        confidences_by_id = {str(item.id): item for item in field_confidences}
        field_items = [item for item in review_case.items if item.scope == ReviewItemScope.FIELD]
        if {str(item.field_confidence_assessment_id) for item in field_items} != set(
            routes_by_confidence
        ):
            raise DomainConflictError("Routing-driven ReviewCase items fail integrity validation")
        covered_reasons: set[str] = set()
        for item in field_items:
            route = routes_by_confidence[str(item.field_confidence_assessment_id)]
            confidence = confidences_by_id.get(str(item.field_confidence_assessment_id))
            if confidence is None:
                raise DomainConflictError("Routing-driven ReviewCase confidence is unavailable")
            verification = confidence.field_verification
            reasons = list(route["reason_codes"])
            covered_reasons.update(reasons)
            if (
                item.item_key != f"FIELD:{confidence.id}"
                or str(item.candidate_field_id) != route["candidate_field_id"]
                or item.candidate_field_id != verification.candidate_field_id
                or item.policy_version != ConfidencePolicyVersion.V2
                or item.priority.value != route["priority"]
                or item.field_path_snapshot != route["field_path"]
                or item.field_path_snapshot != verification.candidate_field_path_snapshot
                or item.candidate_value_type_snapshot != verification.candidate_field_type_snapshot
                or item.candidate_value_snapshot != verification.candidate_field_value_snapshot
                or item.confidence_score_snapshot != confidence.score
                or item.review_reason_codes_snapshot != reasons
                or item.component_breakdown_snapshot
                != {
                    "confidence": confidence.component_breakdown,
                    "routing": route,
                }
            ):
                raise DomainConflictError(
                    "Routing-driven ReviewCase item snapshot fails integrity validation"
                )
        expected_revision_reasons = [
            reason for reason in routing_reasons if reason not in covered_reasons
        ]
        revision_items = [
            item for item in review_case.items if item.scope == ReviewItemScope.REVISION
        ]
        if len(revision_items) != bool(expected_revision_reasons):
            raise DomainConflictError(
                "Routing-driven ReviewCase revision item fails integrity validation"
            )
        if revision_items:
            item = revision_items[0]
            if (
                item.item_key != "REVISION"
                or item.policy_version != ConfidencePolicyVersion.V2
                or item.priority != review_case.priority
                or item.confidence_score_snapshot != review_case.revision_score_snapshot
                or item.review_reason_codes_snapshot != expected_revision_reasons
                or item.component_breakdown_snapshot != review_case.component_breakdown_snapshot
            ):
                raise DomainConflictError(
                    "Routing-driven ReviewCase revision snapshot fails integrity validation"
                )

    @staticmethod
    def _effective_field(
        field_path: str,
        value_type: CandidateValueType,
        value: Any,
        candidate_field_id: uuid.UUID,
        review_decision_id: uuid.UUID | None,
        value_origin: MasterFieldValueOrigin,
    ) -> dict[str, Any]:
        try:
            normalized = normalize_typed_value(value_type, value)
        except ValueError as error:
            raise DomainConflictError(
                f"Invalid effective value for {field_path}: {error}"
            ) from error
        return {
            "field_path": field_path,
            "value_type": value_type,
            "value": normalized,
            "source_candidate_field_id": candidate_field_id,
            "review_decision_id": review_decision_id,
            "value_origin": value_origin,
        }

    @staticmethod
    def _validate_review_integrity(
        review_case: ReviewCase,
        assessment: RevisionConfidenceAssessment,
        field_assessments: list[FieldConfidenceAssessment],
    ) -> None:
        if (
            review_case.candidate_revision_id != assessment.candidate_revision_id
            or review_case.verification_run_id != assessment.verification_run_id
            or review_case.revision_confidence_assessment_id != assessment.id
            or review_case.policy_version != assessment.policy_version
            or review_case.priority != assessment.review_priority
            or review_case.revision_score_snapshot != assessment.score
            or review_case.revision_review_reason_codes_snapshot != assessment.review_reason_codes
            or review_case.component_breakdown_snapshot != assessment.component_breakdown
        ):
            raise DomainConflictError("ReviewCase confidence snapshot fails integrity validation")
        field_by_id = {item.id: item for item in field_assessments}
        decision_types = {
            item.decision.decision for item in review_case.items if item.decision is not None
        }
        if review_case.status == ReviewCaseStatus.RESOLVED:
            if ReviewDecisionType.REQUEST_REVERIFICATION in decision_types:
                expected_outcome = ReviewCaseOutcome.REVERIFICATION_REQUESTED
            elif ReviewDecisionType.REJECT in decision_types:
                expected_outcome = ReviewCaseOutcome.REJECTED
            elif ReviewDecisionType.CORRECT_AND_APPROVE in decision_types:
                expected_outcome = ReviewCaseOutcome.APPROVED_WITH_CORRECTIONS
            else:
                expected_outcome = ReviewCaseOutcome.APPROVED
            if review_case.outcome != expected_outcome:
                raise DomainConflictError("ReviewCase outcome fails decision integrity validation")
        for item in review_case.items:
            if item.decision is None and review_case.status == ReviewCaseStatus.RESOLVED:
                raise DomainConflictError("Resolved ReviewCase has incomplete decisions")
            if item.scope != ReviewItemScope.FIELD:
                if (
                    item.policy_version != assessment.policy_version
                    or item.priority != assessment.review_priority
                    or item.confidence_score_snapshot != assessment.score
                    or item.component_breakdown_snapshot != assessment.component_breakdown
                ):
                    raise DomainConflictError(
                        "Revision ReviewItem snapshot fails integrity validation"
                    )
                continue
            field_assessment = field_by_id.get(item.field_confidence_assessment_id)
            if field_assessment is None:
                raise DomainConflictError("ReviewItem confidence provenance is unavailable")
            verification = field_assessment.field_verification
            if (
                item.candidate_field_id != verification.candidate_field_id
                or item.policy_version != field_assessment.policy_version
                or item.priority != field_assessment.review_priority
                or item.field_path_snapshot != verification.candidate_field_path_snapshot
                or item.candidate_value_type_snapshot != verification.candidate_field_type_snapshot
                or item.candidate_value_snapshot != verification.candidate_field_value_snapshot
                or item.confidence_score_snapshot != field_assessment.score
                or item.review_reason_codes_snapshot != field_assessment.review_reason_codes
                or item.component_breakdown_snapshot != field_assessment.component_breakdown
            ):
                raise DomainConflictError("ReviewItem snapshot fails integrity validation")
            decision = item.decision
            if decision is not None and (
                decision.original_value_type_snapshot != item.candidate_value_type_snapshot
                or decision.original_value_snapshot != item.candidate_value_snapshot
            ):
                raise DomainConflictError("ReviewDecision original snapshot mismatch")

    @staticmethod
    def _timestamp_key(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def _record_changes(
        self,
        master: RecruitmentMaster,
        previous: RecruitmentMasterRevision | None,
        current: RecruitmentMasterRevision,
    ) -> None:
        old_fields = {item.field_path: item for item in previous.fields} if previous else {}
        new_fields = {item.field_path: item for item in current.fields}
        for field_path in sorted(old_fields.keys() | new_fields.keys()):
            old = old_fields.get(field_path)
            new = new_fields.get(field_path)
            if old is None and new is not None:
                change_type = MasterChangeType.ADDED
            elif old is not None and new is None:
                change_type = MasterChangeType.REMOVED
            elif (
                old is not None
                and new is not None
                and (old.value_type != new.value_type or old.value != new.value)
            ):
                change_type = MasterChangeType.UPDATED
            else:
                continue
            self.changes.add(
                MasterChange(
                    recruitment_master_id=master.id,
                    from_master_revision_id=previous.id if previous is not None else None,
                    to_master_revision_id=current.id,
                    field_path=field_path,
                    change_type=change_type,
                    old_value_type=old.value_type if old is not None else None,
                    old_value=copy.deepcopy(old.value) if old is not None else None,
                    new_value_type=new.value_type if new is not None else None,
                    new_value=copy.deepcopy(new.value) if new is not None else None,
                    source_candidate_field_id=(
                        new.source_candidate_field_id
                        if new is not None
                        else old.source_candidate_field_id
                    ),
                    review_decision_id=(
                        new.review_decision_id if new is not None else old.review_decision_id
                    ),
                )
            )
