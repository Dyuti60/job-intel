import uuid
from dataclasses import dataclass

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.candidates import CandidateField
from app.models.discovery import SourceDocument
from app.models.master import (
    MasterField,
    MasterPost,
    MasterPostFact,
    RecruitmentMaster,
    RecruitmentMasterRevision,
    RecruitmentMasterStatus,
)
from app.models.source_registry import RecruitingAuthority, SourceEndpoint


@dataclass(frozen=True)
class PublicMasterRecord:
    master: RecruitmentMaster
    authority: RecruitingAuthority
    revision: RecruitmentMasterRevision
    post: MasterPost | None = None


@dataclass(frozen=True)
class PublicFieldSource:
    candidate_field_id: uuid.UUID
    document: SourceDocument
    endpoint: SourceEndpoint
    authority: RecruitingAuthority


class PublicRecruitmentRepository:
    """Read only from the approved current-master boundary."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_current_active(
        self,
        *,
        authority_code: str | None,
        candidate_key: str | None,
        query: str | None,
    ) -> list[PublicMasterRecord]:
        statement = (
            select(
                RecruitmentMaster,
                RecruitingAuthority,
                RecruitmentMasterRevision,
                MasterPost,
            )
            .join(
                RecruitingAuthority,
                RecruitingAuthority.id == RecruitmentMaster.recruiting_authority_id,
            )
            .join(
                RecruitmentMasterRevision,
                and_(
                    RecruitmentMasterRevision.id == RecruitmentMaster.current_revision_id,
                    RecruitmentMasterRevision.recruitment_master_id == RecruitmentMaster.id,
                ),
            )
            .join(MasterPost, MasterPost.master_revision_id == RecruitmentMasterRevision.id)
            .options(
                selectinload(RecruitmentMasterRevision.fields),
                selectinload(MasterPost.facts).selectinload(MasterPostFact.master_field),
            )
            .where(RecruitmentMaster.status == RecruitmentMasterStatus.ACTIVE)
        )
        legacy_statement = (
            select(RecruitmentMaster, RecruitingAuthority, RecruitmentMasterRevision)
            .join(
                RecruitingAuthority,
                RecruitingAuthority.id == RecruitmentMaster.recruiting_authority_id,
            )
            .join(
                RecruitmentMasterRevision,
                and_(
                    RecruitmentMasterRevision.id == RecruitmentMaster.current_revision_id,
                    RecruitmentMasterRevision.recruitment_master_id == RecruitmentMaster.id,
                ),
            )
            .options(selectinload(RecruitmentMasterRevision.fields))
            .where(
                RecruitmentMaster.status == RecruitmentMasterStatus.ACTIVE,
                ~exists().where(MasterPost.master_revision_id == RecruitmentMasterRevision.id),
            )
        )
        if authority_code is not None:
            statement = statement.where(RecruitingAuthority.code == authority_code)
            legacy_statement = legacy_statement.where(RecruitingAuthority.code == authority_code)
        if candidate_key is not None:
            statement = statement.where(RecruitmentMaster.candidate_key == candidate_key)
            legacy_statement = legacy_statement.where(
                RecruitmentMaster.candidate_key == candidate_key
            )
        if query is not None:
            statement = statement.where(
                or_(
                    MasterPost.name.icontains(query, autoescape=True),
                    RecruitmentMaster.display_name.icontains(query, autoescape=True),
                    RecruitmentMaster.candidate_key.icontains(query, autoescape=True),
                    RecruitingAuthority.name.icontains(query, autoescape=True),
                )
            )
            legacy_statement = legacy_statement.where(
                or_(
                    RecruitmentMaster.display_name.icontains(query, autoescape=True),
                    RecruitmentMaster.candidate_key.icontains(query, autoescape=True),
                    RecruitingAuthority.name.icontains(query, autoescape=True),
                )
            )
        rows = self.session.execute(statement).all()
        legacy_rows = self.session.execute(legacy_statement).all()
        return [PublicMasterRecord(*row) for row in rows] + [
            PublicMasterRecord(*row) for row in legacy_rows
        ]

    def get_current_active(self, public_id: uuid.UUID) -> PublicMasterRecord | None:
        statement = (
            select(
                RecruitmentMaster,
                RecruitingAuthority,
                RecruitmentMasterRevision,
                MasterPost,
            )
            .join(
                RecruitingAuthority,
                RecruitingAuthority.id == RecruitmentMaster.recruiting_authority_id,
            )
            .join(
                RecruitmentMasterRevision,
                and_(
                    RecruitmentMasterRevision.id == RecruitmentMaster.current_revision_id,
                    RecruitmentMasterRevision.recruitment_master_id == RecruitmentMaster.id,
                ),
            )
            .join(MasterPost, MasterPost.master_revision_id == RecruitmentMasterRevision.id)
            .options(
                selectinload(RecruitmentMasterRevision.fields),
                selectinload(MasterPost.facts).selectinload(MasterPostFact.master_field),
            )
            .where(
                MasterPost.public_id == public_id,
                RecruitmentMaster.status == RecruitmentMasterStatus.ACTIVE,
            )
        )
        row = self.session.execute(statement).one_or_none()
        if row is not None:
            return PublicMasterRecord(*row)
        legacy_statement = (
            select(RecruitmentMaster, RecruitingAuthority, RecruitmentMasterRevision)
            .join(
                RecruitingAuthority,
                RecruitingAuthority.id == RecruitmentMaster.recruiting_authority_id,
            )
            .join(
                RecruitmentMasterRevision,
                and_(
                    RecruitmentMasterRevision.id == RecruitmentMaster.current_revision_id,
                    RecruitmentMasterRevision.recruitment_master_id == RecruitmentMaster.id,
                ),
            )
            .options(selectinload(RecruitmentMasterRevision.fields))
            .where(
                RecruitmentMaster.id == public_id,
                RecruitmentMaster.status == RecruitmentMasterStatus.ACTIVE,
                ~exists().where(MasterPost.master_revision_id == RecruitmentMasterRevision.id),
            )
        )
        legacy_row = self.session.execute(legacy_statement).one_or_none()
        return PublicMasterRecord(*legacy_row) if legacy_row is not None else None

    def field_sources(self, master_fields: list[MasterField]) -> dict[uuid.UUID, PublicFieldSource]:
        field_ids = [field.source_candidate_field_id for field in master_fields]
        if not field_ids:
            return {}
        rows = self.session.execute(
            select(CandidateField.id, SourceDocument, SourceEndpoint, RecruitingAuthority)
            .join(SourceDocument, SourceDocument.id == CandidateField.source_document_id)
            .join(SourceEndpoint, SourceEndpoint.id == SourceDocument.source_endpoint_id)
            .join(
                RecruitingAuthority,
                RecruitingAuthority.id == SourceEndpoint.recruiting_authority_id,
            )
            .where(CandidateField.id.in_(field_ids))
        ).all()
        return {
            candidate_field_id: PublicFieldSource(
                candidate_field_id=candidate_field_id,
                document=document,
                endpoint=endpoint,
                authority=authority,
            )
            for candidate_field_id, document, endpoint, authority in rows
        }
