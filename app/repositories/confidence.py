import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.confidence import (
    ConfidencePolicyVersion,
    FieldConfidenceAssessment,
    RevisionConfidenceAssessment,
)


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
