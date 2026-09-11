import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.source_registry import (
    AuthorityStatus,
    AuthorityType,
    SourceClass,
    SourceStatus,
    SourceType,
)
from app.schemas.source_registry import (
    RecruitingAuthorityCreate,
    RecruitingAuthorityRead,
    RecruitingAuthorityUpdate,
    SourceEndpointCreate,
    SourceEndpointRead,
    SourceEndpointUpdate,
)
from app.services.exceptions import DuplicateResourceError, ResourceNotFoundError
from app.services.source_registry import SourceRegistryService

router = APIRouter(tags=["source registry"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def raise_http_error(error: ResourceNotFoundError | DuplicateResourceError) -> None:
    if isinstance(error, ResourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/source-authorities",
    response_model=RecruitingAuthorityRead,
    status_code=status.HTTP_201_CREATED,
)
def create_authority(
    payload: RecruitingAuthorityCreate, session: DatabaseSession
) -> RecruitingAuthorityRead:
    try:
        authority = SourceRegistryService(session).create_authority(payload)
    except (ResourceNotFoundError, DuplicateResourceError) as error:
        raise_http_error(error)
    return RecruitingAuthorityRead.model_validate(authority)


@router.get("/source-authorities", response_model=list[RecruitingAuthorityRead])
def list_authorities(
    session: DatabaseSession,
    authority_type: AuthorityType | None = None,
    status_filter: Annotated[AuthorityStatus | None, Query(alias="status")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RecruitingAuthorityRead]:
    authorities = SourceRegistryService(session).list_authorities(
        authority_type=authority_type,
        status=status_filter,
        offset=offset,
        limit=limit,
    )
    return [RecruitingAuthorityRead.model_validate(item) for item in authorities]


@router.get("/source-authorities/{authority_id}", response_model=RecruitingAuthorityRead)
def get_authority(
    authority_id: uuid.UUID, session: DatabaseSession
) -> RecruitingAuthorityRead:
    try:
        authority = SourceRegistryService(session).get_authority(authority_id)
    except (ResourceNotFoundError, DuplicateResourceError) as error:
        raise_http_error(error)
    return RecruitingAuthorityRead.model_validate(authority)


@router.patch("/source-authorities/{authority_id}", response_model=RecruitingAuthorityRead)
def update_authority(
    authority_id: uuid.UUID,
    payload: RecruitingAuthorityUpdate,
    session: DatabaseSession,
) -> RecruitingAuthorityRead:
    try:
        authority = SourceRegistryService(session).update_authority(authority_id, payload)
    except (ResourceNotFoundError, DuplicateResourceError) as error:
        raise_http_error(error)
    return RecruitingAuthorityRead.model_validate(authority)


@router.post(
    "/source-endpoints",
    response_model=SourceEndpointRead,
    status_code=status.HTTP_201_CREATED,
)
def create_endpoint(
    payload: SourceEndpointCreate, session: DatabaseSession
) -> SourceEndpointRead:
    try:
        endpoint = SourceRegistryService(session).create_endpoint(payload)
    except (ResourceNotFoundError, DuplicateResourceError) as error:
        raise_http_error(error)
    return SourceEndpointRead.model_validate(endpoint)


@router.get("/source-endpoints", response_model=list[SourceEndpointRead])
def list_endpoints(
    session: DatabaseSession,
    recruiting_authority_id: uuid.UUID | None = None,
    status_filter: Annotated[SourceStatus | None, Query(alias="status")] = None,
    discovery_enabled: bool | None = None,
    source_type: SourceType | None = None,
    source_class: SourceClass | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SourceEndpointRead]:
    endpoints = SourceRegistryService(session).list_endpoints(
        recruiting_authority_id=recruiting_authority_id,
        status=status_filter,
        discovery_enabled=discovery_enabled,
        source_type=source_type,
        source_class=source_class,
        offset=offset,
        limit=limit,
    )
    return [SourceEndpointRead.model_validate(item) for item in endpoints]


@router.get("/source-endpoints/{endpoint_id}", response_model=SourceEndpointRead)
def get_endpoint(endpoint_id: uuid.UUID, session: DatabaseSession) -> SourceEndpointRead:
    try:
        endpoint = SourceRegistryService(session).get_endpoint(endpoint_id)
    except (ResourceNotFoundError, DuplicateResourceError) as error:
        raise_http_error(error)
    return SourceEndpointRead.model_validate(endpoint)


@router.patch("/source-endpoints/{endpoint_id}", response_model=SourceEndpointRead)
def update_endpoint(
    endpoint_id: uuid.UUID,
    payload: SourceEndpointUpdate,
    session: DatabaseSession,
) -> SourceEndpointRead:
    try:
        endpoint = SourceRegistryService(session).update_endpoint(endpoint_id, payload)
    except (ResourceNotFoundError, DuplicateResourceError) as error:
        raise_http_error(error)
    return SourceEndpointRead.model_validate(endpoint)
