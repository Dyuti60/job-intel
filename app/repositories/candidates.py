import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.candidates import (
    CandidateField,
    CandidateStatus,
    RecruitmentCandidate,
    RecruitmentCandidateRevision,
)


class RecruitmentCandidateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, candidate: RecruitmentCandidate) -> None:
        self.session.add(candidate)

    def get(self, candidate_id: uuid.UUID) -> RecruitmentCandidate | None:
        return self.session.scalar(
            select(RecruitmentCandidate)
            .options(selectinload(RecruitmentCandidate.revisions))
            .where(RecruitmentCandidate.id == candidate_id)
        )

    def get_by_identity(
        self, recruiting_authority_id: uuid.UUID, candidate_key: str
    ) -> RecruitmentCandidate | None:
        return self.session.scalar(
            select(RecruitmentCandidate).where(
                RecruitmentCandidate.recruiting_authority_id == recruiting_authority_id,
                RecruitmentCandidate.candidate_key == candidate_key,
            )
        )

    def list(
        self,
        *,
        recruiting_authority_id: uuid.UUID | None = None,
        status: CandidateStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[RecruitmentCandidate]:
        statement: Select[tuple[RecruitmentCandidate]] = (
            select(RecruitmentCandidate)
            .options(selectinload(RecruitmentCandidate.revisions))
            .order_by(RecruitmentCandidate.created_at, RecruitmentCandidate.id)
        )
        if recruiting_authority_id is not None:
            statement = statement.where(
                RecruitmentCandidate.recruiting_authority_id == recruiting_authority_id
            )
        if status is not None:
            statement = statement.where(RecruitmentCandidate.status == status)
        return list(self.session.scalars(statement.offset(offset).limit(limit)))


class CandidateRevisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, revision: RecruitmentCandidateRevision) -> None:
        self.session.add(revision)

    def get(self, revision_id: uuid.UUID) -> RecruitmentCandidateRevision | None:
        return self.session.scalar(
            select(RecruitmentCandidateRevision)
            .options(selectinload(RecruitmentCandidateRevision.fields))
            .where(RecruitmentCandidateRevision.id == revision_id)
        )

    def get_by_hash(
        self, candidate_id: uuid.UUID, revision_hash: str
    ) -> RecruitmentCandidateRevision | None:
        return self.session.scalar(
            select(RecruitmentCandidateRevision)
            .options(selectinload(RecruitmentCandidateRevision.fields))
            .where(
                RecruitmentCandidateRevision.recruitment_candidate_id == candidate_id,
                RecruitmentCandidateRevision.revision_hash == revision_hash,
            )
        )

    def list_for_candidate(
        self, candidate_id: uuid.UUID
    ) -> list[RecruitmentCandidateRevision]:
        return list(
            self.session.scalars(
                select(RecruitmentCandidateRevision)
                .options(selectinload(RecruitmentCandidateRevision.fields))
                .where(
                    RecruitmentCandidateRevision.recruitment_candidate_id == candidate_id
                )
                .order_by(RecruitmentCandidateRevision.revision_number)
            )
        )

    def next_revision_number(self, candidate_id: uuid.UUID) -> int:
        current = self.session.scalar(
            select(func.max(RecruitmentCandidateRevision.revision_number)).where(
                RecruitmentCandidateRevision.recruitment_candidate_id == candidate_id
            )
        )
        return (current or 0) + 1

    def has_revision(self, candidate_id: uuid.UUID) -> bool:
        return (
            self.session.scalar(
                select(RecruitmentCandidateRevision.id)
                .where(
                    RecruitmentCandidateRevision.recruitment_candidate_id == candidate_id
                )
                .limit(1)
            )
            is not None
        )


class CandidateFieldRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, field_id: uuid.UUID) -> CandidateField | None:
        return self.session.get(CandidateField, field_id)

    def list_for_revision(self, revision_id: uuid.UUID) -> list[CandidateField]:
        return list(
            self.session.scalars(
                select(CandidateField)
                .where(CandidateField.candidate_revision_id == revision_id)
                .order_by(CandidateField.field_path)
            )
        )
