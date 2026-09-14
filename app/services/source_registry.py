import uuid

from sqlalchemy.exc import IntegrityError
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
from app.repositories.source_registry import (
    RecruitingAuthorityRepository,
    SourceEndpointRepository,
)
from app.schemas.source_registry import (
    RecruitingAuthorityCreate,
    RecruitingAuthorityUpdate,
    SourceEndpointCreate,
    SourceEndpointUpdate,
)
from app.services.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.services.url_normalization import normalize_http_url


class SourceRegistryService:
    def __init__(self, session: Session, *, commit: bool = True) -> None:
        self.session = session
        self.commit = commit
        self.authorities = RecruitingAuthorityRepository(session)
        self.endpoints = SourceEndpointRepository(session)

    def create_authority(self, data: RecruitingAuthorityCreate) -> RecruitingAuthority:
        if self.authorities.get_by_code(data.code) is not None:
            raise DuplicateResourceError(f"Recruiting authority code '{data.code}' already exists")

        authority = RecruitingAuthority(
            code=data.code,
            name=data.name,
            authority_type=data.authority_type,
            official_website_url=normalize_http_url(data.official_website_url),
            status=data.status,
        )
        self.authorities.add(authority)
        self._commit_unique(
            f"Recruiting authority code '{data.code}' already exists"
        )
        self.session.refresh(authority)
        return authority

    def get_authority(self, authority_id: uuid.UUID) -> RecruitingAuthority:
        if (authority := self.authorities.get(authority_id)) is None:
            raise ResourceNotFoundError("Recruiting authority not found")
        return authority

    def list_authorities(
        self,
        *,
        authority_type: AuthorityType | None,
        status: AuthorityStatus | None,
        offset: int,
        limit: int,
    ) -> list[RecruitingAuthority]:
        return self.authorities.list(
            authority_type=authority_type,
            status=status,
            offset=offset,
            limit=limit,
        )

    def update_authority(
        self, authority_id: uuid.UUID, data: RecruitingAuthorityUpdate
    ) -> RecruitingAuthority:
        authority = self.get_authority(authority_id)
        authority.status = data.status
        self._save()
        self.session.refresh(authority)
        return authority

    def create_endpoint(self, data: SourceEndpointCreate) -> SourceEndpoint:
        if self.authorities.get(data.recruiting_authority_id) is None:
            raise ResourceNotFoundError("Recruiting authority not found")

        canonical_url = normalize_http_url(data.canonical_url)
        if self.endpoints.get_by_canonical_url(canonical_url) is not None:
            raise DuplicateResourceError(
                f"Source endpoint '{canonical_url}' is already registered"
            )

        endpoint = SourceEndpoint(
            recruiting_authority_id=data.recruiting_authority_id,
            name=data.name,
            canonical_url=canonical_url,
            source_type=data.source_type,
            source_class=data.source_class,
            status=data.status,
            discovery_enabled=data.discovery_enabled,
            adapter_key=data.adapter_key,
            schedule_group=data.schedule_group,
            poll_interval_minutes=data.poll_interval_minutes,
            priority=data.priority,
            requests_per_minute=data.requests_per_minute,
            last_verified_at=data.last_verified_at,
            provenance_note=data.provenance_note,
        )
        self.endpoints.add(endpoint)
        self._commit_unique(f"Source endpoint '{canonical_url}' is already registered")
        self.session.refresh(endpoint)
        return endpoint

    def get_endpoint(self, endpoint_id: uuid.UUID) -> SourceEndpoint:
        if (endpoint := self.endpoints.get(endpoint_id)) is None:
            raise ResourceNotFoundError("Source endpoint not found")
        return endpoint

    def list_endpoints(
        self,
        *,
        recruiting_authority_id: uuid.UUID | None,
        status: SourceStatus | None,
        discovery_enabled: bool | None,
        source_type: SourceType | None,
        source_class: SourceClass | None,
        offset: int,
        limit: int,
    ) -> list[SourceEndpoint]:
        return self.endpoints.list(
            recruiting_authority_id=recruiting_authority_id,
            status=status,
            discovery_enabled=discovery_enabled,
            source_type=source_type,
            source_class=source_class,
            offset=offset,
            limit=limit,
        )

    def update_endpoint(
        self, endpoint_id: uuid.UUID, data: SourceEndpointUpdate
    ) -> SourceEndpoint:
        endpoint = self.get_endpoint(endpoint_id)
        for field_name in data.model_fields_set:
            setattr(endpoint, field_name, getattr(data, field_name))
        self._save()
        self.session.refresh(endpoint)
        return endpoint

    def _commit_unique(self, message: str) -> None:
        try:
            self._save()
        except IntegrityError as error:
            self.session.rollback()
            raise DuplicateResourceError(message) from error

    def _save(self) -> None:
        self.session.commit() if self.commit else self.session.flush()
