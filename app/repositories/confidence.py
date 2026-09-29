import uuid

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.confidence import (
    ConfidencePolicyVersion,
    FieldConfidenceAssessment,
    RevisionConfidenceAssessment,
)
from app.models.master import MasterPublicationEvent
from app.models.review import ReviewCase, ReviewCaseOutcome, ReviewCaseStatus
from app.models.review_routing import ReviewRoutingAssessment, ReviewRoutingPolicyVersion
from app.models.verification import VerificationRun, VerificationRunStatus


class FieldConfidenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, assessment: FieldConfidenceAssessment) -> None:
        self.session.add(assessment)

    def get_for_policy(
        self,
        field_verification_id: uuid.UUID,
        policy_version: ConfidencePolicyVersion,
    ) -> FieldConfidenceAssessment | None:
        return self.session.scalar(
            select(FieldConfidenceAssessment).where(
                FieldConfidenceAssessment.field_verification_id == field_verification_id,
                FieldConfidenceAssessment.policy_version == policy_version,
            )
        )

    def list_for_run(
        self,
        verification_run_id: uuid.UUID,
        policy_version: ConfidencePolicyVersion,
    ) -> list[FieldConfidenceAssessment]:
        return list(
            self.session.scalars(
                select(FieldConfidenceAssessment)
                .join(FieldConfidenceAssessment.field_verification)
                .where(
                    FieldConfidenceAssessment.policy_version == policy_version,
                    FieldConfidenceAssessment.field_verification.has(
                        verification_run_id=verification_run_id
                    ),
                )
                .order_by(FieldConfidenceAssessment.created_at, FieldConfidenceAssessment.id)
            )
        )


class RevisionConfidenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, assessment: RevisionConfidenceAssessment) -> None:
        self.session.add(assessment)

    def get(self, assessment_id: uuid.UUID) -> RevisionConfidenceAssessment | None:
        return self.session.get(RevisionConfidenceAssessment, assessment_id)

    def get_for_policy(
        self,
        verification_run_id: uuid.UUID,
        policy_version: ConfidencePolicyVersion,
    ) -> RevisionConfidenceAssessment | None:
        return self.session.scalar(
            select(RevisionConfidenceAssessment).where(
                RevisionConfidenceAssessment.verification_run_id == verification_run_id,
                RevisionConfidenceAssessment.policy_version == policy_version,
            )
        )

    def _incremental_publication_statement(self) -> Select[tuple[uuid.UUID]]:
        """Select completed assessments whose current state can produce publication work."""
        newer = aliased(RevisionConfidenceAssessment)
        has_v2 = exists(
            select(newer.id).where(
                newer.verification_run_id == VerificationRun.id,
                newer.policy_version == ConfidencePolicyVersion.V2,
            )
        )
        approved_outcomes = (
            ReviewCaseOutcome.APPROVED,
            ReviewCaseOutcome.APPROVED_WITH_CORRECTIONS,
        )
        v1_approved = exists(
            select(ReviewCase.id).where(
                ReviewCase.revision_confidence_assessment_id
                == RevisionConfidenceAssessment.id,
                ReviewCase.status == ReviewCaseStatus.RESOLVED,
                ReviewCase.outcome.in_(approved_outcomes),
            )
        )
        routing_v2 = aliased(ReviewRoutingAssessment)
        routing_v1 = aliased(ReviewRoutingAssessment)
        has_v2_routing = exists(
            select(routing_v2.id).where(
                routing_v2.revision_confidence_assessment_id
                == RevisionConfidenceAssessment.id,
                routing_v2.policy_version == ReviewRoutingPolicyVersion.V2,
            )
        )

        def routing_actionable(routing, policy):
            approved = exists(
                select(ReviewCase.id).where(
                    ReviewCase.review_routing_assessment_id == routing.id,
                    ReviewCase.status == ReviewCaseStatus.RESOLVED,
                    ReviewCase.outcome.in_(approved_outcomes),
                )
            )
            return exists(
                select(routing.id).where(
                    routing.revision_confidence_assessment_id
                    == RevisionConfidenceAssessment.id,
                    routing.policy_version == policy,
                    or_(routing.review_required.is_(False), approved),
                )
            )

        v2_actionable = routing_actionable(routing_v2, ReviewRoutingPolicyVersion.V2)
        v1_routing_actionable = routing_actionable(
            routing_v1, ReviewRoutingPolicyVersion.V1
        )
        return (
            select(RevisionConfidenceAssessment.id)
            .join(
                VerificationRun,
                VerificationRun.id == RevisionConfidenceAssessment.verification_run_id,
            )
            .outerjoin(
                MasterPublicationEvent,
                MasterPublicationEvent.revision_confidence_assessment_id
                == RevisionConfidenceAssessment.id,
            )
            .where(
                VerificationRun.status == VerificationRunStatus.COMPLETED,
                or_(
                    RevisionConfidenceAssessment.policy_version == ConfidencePolicyVersion.V2,
                    and_(
                        RevisionConfidenceAssessment.policy_version
                        == ConfidencePolicyVersion.V1,
                        ~has_v2,
                    ),
                ),
                MasterPublicationEvent.id.is_(None),
                or_(
                    and_(
                        RevisionConfidenceAssessment.policy_version
                        == ConfidencePolicyVersion.V1,
                        or_(
                            RevisionConfidenceAssessment.review_required.is_(False),
                            v1_approved,
                        ),
                    ),
                    and_(
                        RevisionConfidenceAssessment.policy_version
                        == ConfidencePolicyVersion.V2,
                        or_(
                            v2_actionable,
                            and_(~has_v2_routing, v1_routing_actionable),
                        ),
                    ),
                ),
            )
        )

    def count_incremental_publication_ids(self) -> int:
        statement = self._incremental_publication_statement()
        return int(
            self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )

    def list_pending_publication_ids(self, *, limit: int) -> list[uuid.UUID]:
        """Return deterministic incremental publication work, bounded by ``limit``."""
        statement = self._incremental_publication_statement().order_by(
            RevisionConfidenceAssessment.created_at,
            RevisionConfidenceAssessment.id,
        )
        return list(self.session.scalars(statement.limit(limit)))
