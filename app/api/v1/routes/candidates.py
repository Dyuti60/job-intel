import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.candidates import CandidateStatus
from app.schemas.candidates import (
    CandidateFieldRead,
    RecruitmentCandidateCreate,
    RecruitmentCandidateRead,
    RecruitmentCandidateRevisionCreate,
    RecruitmentCandidateRevisionRead,
    RecruitmentCandidateUpdate,
)
from app.services.candidates import CandidateService
from app.services.exceptions import (
    DomainConflictError,
    DuplicateResourceError,
    ResourceNotFoundError,
)

router = APIRouter(tags=["recruitment candidates"])
DatabaseSession = Annotated[Session, Depends(get_db)]
CandidateError = ResourceNotFoundError | DuplicateResourceError | DomainConflictError


def raise_http_error(error: CandidateError) -> None:
    if isinstance(error, ResourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/recruitment-candidates",
    response_model=RecruitmentCandidateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_candidate(
    payload: RecruitmentCandidateCreate,
    session: DatabaseSession,
) -> RecruitmentCandidateRead:
    try:
        candidate = CandidateService(session).create_candidate(payload)
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return RecruitmentCandidateRead.model_validate(candidate)


@router.get(
    "/recruitment-candidates",
    response_model=list[RecruitmentCandidateRead],
)
def list_candidates(
    session: DatabaseSession,
    recruiting_authority_id: uuid.UUID | None = None,
    status_filter: Annotated[CandidateStatus | None, Query(alias="status")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RecruitmentCandidateRead]:
    candidates = CandidateService(session).list_candidates(
        recruiting_authority_id=recruiting_authority_id,
        status=status_filter,
        offset=offset,
        limit=limit,
    )
    return [RecruitmentCandidateRead.model_validate(item) for item in candidates]


@router.get(
    "/recruitment-candidates/{candidate_id}",
    response_model=RecruitmentCandidateRead,
)
def get_candidate(
    candidate_id: uuid.UUID, session: DatabaseSession
) -> RecruitmentCandidateRead:
    try:
        candidate = CandidateService(session).get_candidate(candidate_id)
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return RecruitmentCandidateRead.model_validate(candidate)


@router.patch(
    "/recruitment-candidates/{candidate_id}",
    response_model=RecruitmentCandidateRead,
)
def update_candidate(
    candidate_id: uuid.UUID,
    payload: RecruitmentCandidateUpdate,
    session: DatabaseSession,
) -> RecruitmentCandidateRead:
    try:
        candidate = CandidateService(session).update_candidate_status(
            candidate_id, payload.status
        )
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return RecruitmentCandidateRead.model_validate(candidate)


@router.post(
    "/recruitment-candidates/{candidate_id}/revisions",
    response_model=RecruitmentCandidateRevisionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_revision(
    candidate_id: uuid.UUID,
    payload: RecruitmentCandidateRevisionCreate,
    response: Response,
    session: DatabaseSession,
) -> RecruitmentCandidateRevisionRead:
    try:
        revision, created = CandidateService(session).create_revision(candidate_id, payload)
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    if not created:
        response.status_code = status.HTTP_200_OK
    return RecruitmentCandidateRevisionRead.model_validate(revision)


@router.get(
    "/recruitment-candidates/{candidate_id}/revisions",
    response_model=list[RecruitmentCandidateRevisionRead],
)
def list_revisions(
    candidate_id: uuid.UUID, session: DatabaseSession
) -> list[RecruitmentCandidateRevisionRead]:
    try:
        revisions = CandidateService(session).list_revisions(candidate_id)
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return [RecruitmentCandidateRevisionRead.model_validate(item) for item in revisions]


@router.get(
    "/candidate-revisions/{revision_id}",
    response_model=RecruitmentCandidateRevisionRead,
)
def get_revision(
    revision_id: uuid.UUID, session: DatabaseSession
) -> RecruitmentCandidateRevisionRead:
    try:
        revision = CandidateService(session).get_revision(revision_id)
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return RecruitmentCandidateRevisionRead.model_validate(revision)


@router.get(
    "/candidate-revisions/{revision_id}/fields",
    response_model=list[CandidateFieldRead],
)
def list_revision_fields(
    revision_id: uuid.UUID, session: DatabaseSession
) -> list[CandidateFieldRead]:
    try:
        fields = CandidateService(session).list_fields(revision_id)
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return [CandidateFieldRead.model_validate(item) for item in fields]
