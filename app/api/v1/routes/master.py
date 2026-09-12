import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.master import RecruitmentMasterStatus
from app.schemas.master import (
    MasterChangeRead,
    MasterPublicationEventRead,
    MasterPublishRequest,
    MasterPublishResult,
    MasterRevisionRead,
    MasterRevisionSummary,
    RecruitmentMasterRead,
    RecruitmentMasterSummary,
)
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.master import MasterPublisherService

router = APIRouter(tags=["recruitment-master"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def raise_http_error(error: ResourceNotFoundError | DomainConflictError) -> None:
    error_status = (
        status.HTTP_404_NOT_FOUND
        if isinstance(error, ResourceNotFoundError)
        else status.HTTP_409_CONFLICT
    )
    raise HTTPException(status_code=error_status, detail=str(error)) from error


@router.post(
    "/recruitment-master/publish",
    response_model=MasterPublishResult,
    status_code=status.HTTP_201_CREATED,
)
def publish_recruitment_master(
    payload: MasterPublishRequest,
    response: Response,
    session: DatabaseSession,
) -> MasterPublishResult:
    try:
        master, revision, event, revision_created = MasterPublisherService(session).publish(
            payload.revision_confidence_assessment_id
        )
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not revision_created:
        response.status_code = status.HTTP_200_OK
    return MasterPublishResult(
        master=RecruitmentMasterRead.model_validate(master),
        master_revision=MasterRevisionRead.model_validate(revision),
        publication_event=MasterPublicationEventRead.model_validate(event),
        revision_created=revision_created,
    )


@router.get("/recruitment-master", response_model=list[RecruitmentMasterSummary])
def list_recruitment_masters(
    session: DatabaseSession,
    recruiting_authority_id: uuid.UUID | None = None,
    status_filter: Annotated[RecruitmentMasterStatus | None, Query(alias="status")] = None,
    candidate_key: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RecruitmentMasterSummary]:
    masters = MasterPublisherService(session).list_masters(
        recruiting_authority_id=recruiting_authority_id,
        status=status_filter,
        candidate_key=candidate_key,
        offset=offset,
        limit=limit,
    )
    return [RecruitmentMasterSummary.model_validate(item) for item in masters]


@router.get("/recruitment-master/{master_id}", response_model=RecruitmentMasterRead)
def get_recruitment_master(master_id: uuid.UUID, session: DatabaseSession) -> RecruitmentMasterRead:
    try:
        master = MasterPublisherService(session).get_master(master_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return RecruitmentMasterRead.model_validate(master)


@router.get(
    "/recruitment-master/{master_id}/revisions",
    response_model=list[MasterRevisionSummary],
)
def list_master_revisions(
    master_id: uuid.UUID, session: DatabaseSession
) -> list[MasterRevisionSummary]:
    try:
        revisions = MasterPublisherService(session).list_revisions(master_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return [MasterRevisionSummary.model_validate(item) for item in revisions]


@router.get("/recruitment-master-revisions/{revision_id}", response_model=MasterRevisionRead)
def get_master_revision(revision_id: uuid.UUID, session: DatabaseSession) -> MasterRevisionRead:
    try:
        revision = MasterPublisherService(session).get_revision(revision_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return MasterRevisionRead.model_validate(revision)


@router.get("/recruitment-master/{master_id}/changes", response_model=list[MasterChangeRead])
def list_master_changes(master_id: uuid.UUID, session: DatabaseSession) -> list[MasterChangeRead]:
    try:
        changes = MasterPublisherService(session).list_changes(master_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return [MasterChangeRead.model_validate(item) for item in changes]


@router.get(
    "/recruitment-master/{master_id}/publication-events",
    response_model=list[MasterPublicationEventRead],
)
def list_master_publication_events(
    master_id: uuid.UUID, session: DatabaseSession
) -> list[MasterPublicationEventRead]:
    try:
        events = MasterPublisherService(session).list_events(master_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return [MasterPublicationEventRead.model_validate(item) for item in events]
