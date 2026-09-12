import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.candidates import RecruitmentCandidateRevision
from app.models.discovery import SourceDocument
from app.models.evidence import Evidence
from app.models.verification import (
    FieldVerification,
    FieldVerificationStatus,
    VerificationEvidenceAssessment,
    VerificationRun,
    VerificationRunStatus,
    VerificationTriggerType,
)


class VerificationRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, run: VerificationRun) -> None:
        self.session.add(run)

    def get(self, run_id: uuid.UUID) -> VerificationRun | None:
        return self.session.scalar(
            select(VerificationRun)
            .options(selectinload(VerificationRun.field_verifications))
            .where(VerificationRun.id == run_id)
        )

    def list(
        self,
        *,
        candidate_revision_id: uuid.UUID | None = None,
        candidate_id: uuid.UUID | None = None,
        status: VerificationRunStatus | None = None,
        trigger_type: VerificationTriggerType | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[VerificationRun]:
        statement: Select[tuple[VerificationRun]] = select(VerificationRun).order_by(
            VerificationRun.created_at.desc(), VerificationRun.id
        )
        if candidate_id is not None:
            statement = statement.join(RecruitmentCandidateRevision).where(
                RecruitmentCandidateRevision.recruitment_candidate_id == candidate_id
            )
        if candidate_revision_id is not None:
            statement = statement.where(
                VerificationRun.candidate_revision_id == candidate_revision_id
            )
        if status is not None:
            statement = statement.where(VerificationRun.status == status)
        if trigger_type is not None:
            statement = statement.where(VerificationRun.trigger_type == trigger_type)
        return list(self.session.scalars(statement.offset(offset).limit(limit)))


class FieldVerificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, verification: FieldVerification) -> None:
        self.session.add(verification)

    def get(self, verification_id: uuid.UUID) -> FieldVerification | None:
        return self.session.scalar(
            select(FieldVerification)
            .execution_options(populate_existing=True)
            .options(
                selectinload(FieldVerification.assessments)
                .selectinload(VerificationEvidenceAssessment.evidence)
                .selectinload(Evidence.source_document)
                .selectinload(SourceDocument.source_endpoint)
            )
            .where(FieldVerification.id == verification_id)
        )

    def get_for_run_field(
        self, run_id: uuid.UUID, field_id: uuid.UUID
    ) -> FieldVerification | None:
        return self.session.scalar(
            select(FieldVerification).where(
                FieldVerification.verification_run_id == run_id,
                FieldVerification.candidate_field_id == field_id,
            )
        )

    def list_for_run(self, run_id: uuid.UUID) -> list[FieldVerification]:
        return list(
            self.session.scalars(
                select(FieldVerification)
                .execution_options(populate_existing=True)
                .options(
                    selectinload(FieldVerification.assessments)
                    .selectinload(VerificationEvidenceAssessment.evidence)
                    .selectinload(Evidence.source_document)
                    .selectinload(SourceDocument.source_endpoint)
                )
                .where(FieldVerification.verification_run_id == run_id)
                .order_by(FieldVerification.created_at, FieldVerification.id)
            )
        )

    def finalized_count(self, run_id: uuid.UUID) -> int:
        return int(
            self.session.scalar(
                select(func.count(FieldVerification.id)).where(
                    FieldVerification.verification_run_id == run_id,
                    FieldVerification.status == FieldVerificationStatus.FINALIZED,
                )
            )
            or 0
        )


class VerificationAssessmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, assessment: VerificationEvidenceAssessment) -> None:
        self.session.add(assessment)

    def get_for_field_evidence(
        self, field_verification_id: uuid.UUID, evidence_id: uuid.UUID
    ) -> VerificationEvidenceAssessment | None:
        return self.session.scalar(
            select(VerificationEvidenceAssessment).where(
                VerificationEvidenceAssessment.field_verification_id
                == field_verification_id,
                VerificationEvidenceAssessment.evidence_id == evidence_id,
            )
        )
