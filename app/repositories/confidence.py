import uuid

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.confidence import (
    ConfidencePolicyVersion,
    FieldConfidenceAssessment,
    RevisionConfidenceAssessment,
)
from app.models.master import MasterPublicationEvent
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

    def list_pending_publication_ids(self, *, limit: int) -> list[uuid.UUID]:
        """Return completed-run assessments without a successful publication event."""
        newer = aliased(RevisionConfidenceAssessment)
        has_v2 = exists(
            select(newer.id).where(
                newer.verification_run_id == VerificationRun.id,
                newer.policy_version == ConfidencePolicyVersion.V2,
            )
        )
        return list(
            self.session.scalars(
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
                )
                .order_by(
                    RevisionConfidenceAssessment.created_at,
                    RevisionConfidenceAssessment.id,
                )
                .limit(limit)
            )
        )
