import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.confidence import ReviewPriority
from app.models.review import ReviewCaseStatus
from app.schemas.review import (
    ApprovedProjectionRead,
    ReviewCaseCreate,
    ReviewCaseDetail,
    ReviewCaseSummary,
    ReviewDecisionCreate,
    ReviewDecisionRead,
    ReviewItemRead,
)
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.review import ReviewService

router = APIRouter(tags=["review"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def raise_http_error(error: ResourceNotFoundError | DomainConflictError) -> None:
    error_status = (
        status.HTTP_404_NOT_FOUND
        if isinstance(error, ResourceNotFoundError)
        else status.HTTP_409_CONFLICT
    )
    raise HTTPException(status_code=error_status, detail=str(error)) from error


@router.post(
    "/review-cases",
    response_model=ReviewCaseDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_review_case(
    payload: ReviewCaseCreate,
    response: Response,
    session: DatabaseSession,
) -> ReviewCaseDetail:
    try:
        review_case, created = ReviewService(session).create_case(
            payload.revision_confidence_assessment_id
        )
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not created:
        response.status_code = status.HTTP_200_OK
    return ReviewCaseDetail.model_validate(review_case)


@router.get("/review-cases", response_model=list[ReviewCaseSummary])
def list_review_cases(
    session: DatabaseSession,
    status_filter: Annotated[ReviewCaseStatus | None, Query(alias="status")] = None,
    priority: ReviewPriority | None = None,
    candidate_revision_id: uuid.UUID | None = None,
    verification_run_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ReviewCaseSummary]:
    cases = ReviewService(session).list_cases(
        status=status_filter,
        priority=priority,
        candidate_revision_id=candidate_revision_id,
        verification_run_id=verification_run_id,
        offset=offset,
        limit=limit,
    )
    return [ReviewCaseSummary.model_validate(item) for item in cases]


@router.get("/review-cases/{case_id}", response_model=ReviewCaseDetail)
def get_review_case(case_id: uuid.UUID, session: DatabaseSession) -> ReviewCaseDetail:
    try:
        review_case = ReviewService(session).get_case(case_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return ReviewCaseDetail.model_validate(review_case)


@router.post("/review-cases/{case_id}/start", response_model=ReviewCaseDetail)
def start_review_case(case_id: uuid.UUID, session: DatabaseSession) -> ReviewCaseDetail:
    try:
        review_case = ReviewService(session).start_case(case_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return ReviewCaseDetail.model_validate(review_case)


@router.post("/review-cases/{case_id}/cancel", response_model=ReviewCaseDetail)
def cancel_review_case(
    case_id: uuid.UUID,
    response: Response,
    session: DatabaseSession,
) -> ReviewCaseDetail:
    try:
        review_case, changed = ReviewService(session).cancel_case(case_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not changed:
        response.status_code = status.HTTP_200_OK
    return ReviewCaseDetail.model_validate(review_case)


@router.post("/review-cases/{case_id}/resolve", response_model=ReviewCaseDetail)
def resolve_review_case(
    case_id: uuid.UUID,
    response: Response,
    session: DatabaseSession,
) -> ReviewCaseDetail:
    try:
        review_case, changed = ReviewService(session).resolve_case(case_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not changed:
        response.status_code = status.HTTP_200_OK
    return ReviewCaseDetail.model_validate(review_case)


@router.get("/review-items/{item_id}", response_model=ReviewItemRead)
def get_review_item(item_id: uuid.UUID, session: DatabaseSession) -> ReviewItemRead:
    try:
        item = ReviewService(session).get_item(item_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return ReviewItemRead.model_validate(item)


@router.post(
    "/review-items/{item_id}/decision",
    response_model=ReviewDecisionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_review_decision(
    item_id: uuid.UUID,
    payload: ReviewDecisionCreate,
    response: Response,
    session: DatabaseSession,
) -> ReviewDecisionRead:
    try:
        decision, created = ReviewService(session).decide_item(item_id, payload)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not created:
        response.status_code = status.HTTP_200_OK
    return ReviewDecisionRead.model_validate(decision)


@router.get(
    "/review-cases/{case_id}/approved-projection",
    response_model=ApprovedProjectionRead,
)
def get_approved_projection(case_id: uuid.UUID, session: DatabaseSession) -> ApprovedProjectionRead:
    try:
        projection = ReviewService(session).approved_projection(case_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return ApprovedProjectionRead.model_validate(projection)
