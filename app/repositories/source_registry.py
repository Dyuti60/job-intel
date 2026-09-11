import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.source_registry import (
    AuthorityStatus,
    AuthorityType,
    RecruitingAuthority,
    SourceClass,
    SourceEndpoint,
    SourceStatus,
    SourceType,
)


class RecruitingAuthorityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, authority: RecruitingAuthority) -> None:
        self.session.add(authority)

    def get(self, authority_id: uuid.UUID) -> RecruitingAuthority | None:
        return self.session.get(RecruitingAuthority, authority_id)

    def get_by_code(self, code: str) -> RecruitingAuthority | None:
        return self.session.scalar(
            select(RecruitingAuthority).where(RecruitingAuthority.code == code)
        )

    def list(
        self,
        *,
        authority_type: AuthorityType | None = None,
        status: AuthorityStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[RecruitingAuthority]:
        statement = select(RecruitingAuthority).order_by(RecruitingAuthority.code)
        if authority_type is not None:
            statement = statement.where(RecruitingAuthority.authority_type == authority_type)
        if status is not None:
            statement = statement.where(RecruitingAuthority.status == status)
        return list(self.session.scalars(statement.offset(offset).limit(limit)))


class SourceEndpointRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, endpoint: SourceEndpoint) -> None:
        self.session.add(endpoint)

    def get(self, endpoint_id: uuid.UUID) -> SourceEndpoint | None:
        return self.session.get(SourceEndpoint, endpoint_id)

    def get_by_canonical_url(self, canonical_url: str) -> SourceEndpoint | None:
        return self.session.scalar(
            select(SourceEndpoint).where(SourceEndpoint.canonical_url == canonical_url)
        )

    def list(
        self,
        *,
        recruiting_authority_id: uuid.UUID | None = None,
        status: SourceStatus | None = None,
        discovery_enabled: bool | None = None,
        source_type: SourceType | None = None,
        source_class: SourceClass | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[SourceEndpoint]:
        statement: Select[tuple[SourceEndpoint]] = select(SourceEndpoint).order_by(
            SourceEndpoint.created_at, SourceEndpoint.id
        )
        if recruiting_authority_id is not None:
            statement = statement.where(
                SourceEndpoint.recruiting_authority_id == recruiting_authority_id
            )
        if status is not None:
            statement = statement.where(SourceEndpoint.status == status)
        if discovery_enabled is not None:
            statement = statement.where(SourceEndpoint.discovery_enabled == discovery_enabled)
        if source_type is not None:
            statement = statement.where(SourceEndpoint.source_type == source_type)
        if source_class is not None:
            statement = statement.where(SourceEndpoint.source_class == source_class)
        return list(self.session.scalars(statement.offset(offset).limit(limit)))
