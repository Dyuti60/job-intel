import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.confidence import (
    FieldConfidenceRead,
    RevisionConfidenceDetail,
    RevisionConfidenceRead,
)
from app.services.confidence import ConfidenceService
from app.services.confidence_policy import ConfidencePolicyV1
from app.services.exceptions import DomainConflictError, ResourceNotFoundError

router = APIRouter(tags=["confidence"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def get_confidence_policy() -> ConfidencePolicyV1:
    return ConfidencePolicyV1.from_settings(get_settings())


ConfidencePolicy = Annotated[ConfidencePolicyV1, Depends(get_confidence_policy)]


def raise_http_error(error: ResourceNotFoundError | DomainConflictError) -> None:
    error_status = (
        status.HTTP_404_NOT_FOUND
        if isinstance(error, ResourceNotFoundError)
        else status.HTTP_409_CONFLICT
    )
    raise HTTPException(status_code=error_status, detail=str(error)) from error


@router.post(
    "/field-verifications/{verification_id}/confidence",
    response_model=FieldConfidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def calculate_field_confidence(
    verification_id: uuid.UUID,
    response: Response,
    session: DatabaseSession,
    policy: ConfidencePolicy,
) -> FieldConfidenceRead:
    try:
        assessment, created = ConfidenceService(session, policy).score_field(verification_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not created:
        response.status_code = status.HTTP_200_OK
    return FieldConfidenceRead.model_validate(assessment)


@router.get(
    "/field-verifications/{verification_id}/confidence",
    response_model=FieldConfidenceRead,
)
def get_field_confidence(
    verification_id: uuid.UUID,
    session: DatabaseSession,
    policy: ConfidencePolicy,
) -> FieldConfidenceRead:
    try:
        assessment = ConfidenceService(session, policy).get_field_assessment(verification_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return FieldConfidenceRead.model_validate(assessment)


@router.post(
    "/verification-runs/{run_id}/confidence",
    response_model=RevisionConfidenceDetail,
    status_code=status.HTTP_201_CREATED,
)
def calculate_revision_confidence(
    run_id: uuid.UUID,
    response: Response,
    session: DatabaseSession,
    policy: ConfidencePolicy,
) -> RevisionConfidenceDetail:
    try:
        assessment, field_assessments, created = ConfidenceService(session, policy).score_run(
            run_id
        )
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not created:
        response.status_code = status.HTTP_200_OK
    return _revision_detail(assessment, field_assessments)


@router.get(
    "/verification-runs/{run_id}/confidence",
    response_model=RevisionConfidenceDetail,
)
def get_revision_confidence(
    run_id: uuid.UUID,
    session: DatabaseSession,
    policy: ConfidencePolicy,
) -> RevisionConfidenceDetail:
    try:
        assessment, field_assessments = ConfidenceService(session, policy).get_revision_assessment(
            run_id
        )
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return _revision_detail(assessment, field_assessments)


def _revision_detail(assessment, field_assessments) -> RevisionConfidenceDetail:
    data = RevisionConfidenceRead.model_validate(assessment).model_dump()
    data["field_assessments"] = [
        FieldConfidenceRead.model_validate(item) for item in field_assessments
    ]
    return RevisionConfidenceDetail.model_validate(data)
