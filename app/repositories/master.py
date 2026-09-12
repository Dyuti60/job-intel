import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.master import (
    MasterChange,
    MasterPublicationEvent,
    RecruitmentMaster,
    RecruitmentMasterRevision,
    RecruitmentMasterStatus,
)


class RecruitmentMasterRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, master: RecruitmentMaster) -> None:
        self.session.add(master)

    def get(self, master_id: uuid.UUID) -> RecruitmentMaster | None:
        return self.session.scalar(
            select(RecruitmentMaster)
            .execution_options(populate_existing=True)
            .options(
                selectinload(RecruitmentMaster.current_revision).selectinload(
                    RecruitmentMasterRevision.fields
                )
            )
            .where(RecruitmentMaster.id == master_id)
        )

    def get_by_identity(
        self, recruiting_authority_id: uuid.UUID, candidate_key: str
    ) -> RecruitmentMaster | None:
        return self.session.scalar(
            select(RecruitmentMaster)
            .execution_options(populate_existing=True)
            .options(
                selectinload(RecruitmentMaster.current_revision).selectinload(
                    RecruitmentMasterRevision.fields
                )
            )
            .where(
                RecruitmentMaster.recruiting_authority_id == recruiting_authority_id,
                RecruitmentMaster.candidate_key == candidate_key,
            )
        )

    def list(
        self,
        *,
        recruiting_authority_id: uuid.UUID | None,
        status: RecruitmentMasterStatus | None,
        candidate_key: str | None,
        offset: int,
        limit: int,
    ) -> list[RecruitmentMaster]:
        statement: Select[tuple[RecruitmentMaster]] = (
            select(RecruitmentMaster)
            .options(selectinload(RecruitmentMaster.current_revision))
            .order_by(RecruitmentMaster.last_published_at.desc(), RecruitmentMaster.id)
        )
        if recruiting_authority_id is not None:
            statement = statement.where(
                RecruitmentMaster.recruiting_authority_id == recruiting_authority_id
            )
        if status is not None:
            statement = statement.where(RecruitmentMaster.status == status)
        if candidate_key is not None:
            statement = statement.where(RecruitmentMaster.candidate_key == candidate_key)
        return list(self.session.scalars(statement.offset(offset).limit(limit)))


class MasterRevisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, revision: RecruitmentMasterRevision) -> None:
        self.session.add(revision)

    def get(self, revision_id: uuid.UUID) -> RecruitmentMasterRevision | None:
        return self.session.scalar(
            select(RecruitmentMasterRevision)
            .options(selectinload(RecruitmentMasterRevision.fields))
            .where(RecruitmentMasterRevision.id == revision_id)
        )

    def get_by_hash(
        self, master_id: uuid.UUID, projection_hash: str
    ) -> RecruitmentMasterRevision | None:
        return self.session.scalar(
            select(RecruitmentMasterRevision)
            .options(selectinload(RecruitmentMasterRevision.fields))
            .where(
                RecruitmentMasterRevision.recruitment_master_id == master_id,
                RecruitmentMasterRevision.projection_hash == projection_hash,
            )
        )

    def list_for_master(self, master_id: uuid.UUID) -> list[RecruitmentMasterRevision]:
        return list(
            self.session.scalars(
                select(RecruitmentMasterRevision)
                .options(selectinload(RecruitmentMasterRevision.fields))
                .where(RecruitmentMasterRevision.recruitment_master_id == master_id)
                .order_by(RecruitmentMasterRevision.revision_number)
            )
        )

    def next_revision_number(self, master_id: uuid.UUID) -> int:
        current = self.session.scalar(
            select(func.max(RecruitmentMasterRevision.revision_number)).where(
                RecruitmentMasterRevision.recruitment_master_id == master_id
            )
        )
        return (current or 0) + 1


class MasterPublicationEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, event: MasterPublicationEvent) -> None:
        self.session.add(event)

    def get_by_confidence_assessment(
        self, assessment_id: uuid.UUID
    ) -> MasterPublicationEvent | None:
        return self.session.scalar(
            select(MasterPublicationEvent).where(
                MasterPublicationEvent.revision_confidence_assessment_id == assessment_id
            )
        )

    def list_for_master(self, master_id: uuid.UUID) -> list[MasterPublicationEvent]:
        return list(
            self.session.scalars(
                select(MasterPublicationEvent)
                .where(MasterPublicationEvent.recruitment_master_id == master_id)
                .order_by(
                    MasterPublicationEvent.published_or_verified_at,
                    MasterPublicationEvent.id,
                )
            )
        )


class MasterChangeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, change: MasterChange) -> None:
        self.session.add(change)

    def list_for_master(self, master_id: uuid.UUID) -> list[MasterChange]:
        return list(
            self.session.scalars(
                select(MasterChange)
                .where(MasterChange.recruitment_master_id == master_id)
                .order_by(MasterChange.created_at, MasterChange.id)
            )
        )
