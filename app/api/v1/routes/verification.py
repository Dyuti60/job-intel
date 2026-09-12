import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.verification import VerificationRunStatus, VerificationTriggerType
from app.schemas.verification import (
    FieldVerificationFinalize,
    FieldVerificationRead,
    VerificationEvidenceAssessmentCreate,
    VerificationRunComplete,
    VerificationRunCreate,
    VerificationRunRead,
)
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.verification import VerificationService

router = APIRouter(tags=["verification"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def raise_http_error(error: ResourceNotFoundError | DomainConflictError) -> None:
    error_status = (
        status.HTTP_404_NOT_FOUND
        if isinstance(error, ResourceNotFoundError)
        else status.HTTP_409_CONFLICT
    )
    raise HTTPException(status_code=error_status, detail=str(error)) from error


@router.post(
    "/verification-runs",
    response_model=VerificationRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_verification_run(
    payload: VerificationRunCreate, session: DatabaseSession
) -> VerificationRunRead:
    try:
        run = VerificationService(session).create_run(payload)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return VerificationRunRead.model_validate(run)


@router.get("/verification-runs", response_model=list[VerificationRunRead])
def list_verification_runs(
    session: DatabaseSession,
    candidate_revision_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    status_filter: Annotated[
        VerificationRunStatus | None, Query(alias="status")
    ] = None,
    trigger_type: VerificationTriggerType | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[VerificationRunRead]:
    runs = VerificationService(session).list_runs(
        candidate_revision_id=candidate_revision_id,
        candidate_id=candidate_id,
        status=status_filter,
        trigger_type=trigger_type,
        offset=offset,
        limit=limit,
    )
    return [VerificationRunRead.model_validate(item) for item in runs]


@router.get("/verification-runs/{run_id}", response_model=VerificationRunRead)
def get_verification_run(
    run_id: uuid.UUID, session: DatabaseSession
) -> VerificationRunRead:
    try:
        run = VerificationService(session).get_run(run_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return VerificationRunRead.model_validate(run)


@router.post("/verification-runs/{run_id}/start", response_model=VerificationRunRead)
def start_verification_run(
    run_id: uuid.UUID, session: DatabaseSession
) -> VerificationRunRead:
    try:
        run = VerificationService(session).start_run(run_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return VerificationRunRead.model_validate(run)


@router.post(
    "/verification-runs/{run_id}/complete",
    response_model=VerificationRunRead,
)
def complete_verification_run(
    run_id: uuid.UUID,
    payload: VerificationRunComplete,
    session: DatabaseSession,
) -> VerificationRunRead:
    try:
        run = VerificationService(session).complete_run(run_id, payload)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return VerificationRunRead.model_validate(run)


@router.post(
    "/verification-runs/{run_id}/fields/{candidate_field_id}",
    response_model=FieldVerificationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_field_verification(
    run_id: uuid.UUID,
    candidate_field_id: uuid.UUID,
    response: Response,
    session: DatabaseSession,
) -> FieldVerificationRead:
    try:
        verification, created = VerificationService(
            session
        ).create_field_verification(run_id, candidate_field_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not created:
        response.status_code = status.HTTP_200_OK
    return FieldVerificationRead.model_validate(verification)


@router.get(
    "/verification-runs/{run_id}/fields",
    response_model=list[FieldVerificationRead],
)
def list_field_verifications(
    run_id: uuid.UUID, session: DatabaseSession
) -> list[FieldVerificationRead]:
    try:
        verifications = VerificationService(session).list_field_verifications(run_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return [FieldVerificationRead.model_validate(item) for item in verifications]


@router.get(
    "/field-verifications/{verification_id}",
    response_model=FieldVerificationRead,
)
def get_field_verification(
    verification_id: uuid.UUID, session: DatabaseSession
) -> FieldVerificationRead:
    try:
        verification = VerificationService(session).get_field_verification(
            verification_id
        )
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return FieldVerificationRead.model_validate(verification)


@router.post(
    "/field-verifications/{verification_id}/evidence",
    response_model=FieldVerificationRead,
    status_code=status.HTTP_201_CREATED,
)
def add_verification_evidence(
    verification_id: uuid.UUID,
    payload: VerificationEvidenceAssessmentCreate,
    response: Response,
    session: DatabaseSession,
) -> FieldVerificationRead:
    try:
        verification, created = VerificationService(session).add_assessment(
            verification_id, payload
        )
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not created:
        response.status_code = status.HTTP_200_OK
    return FieldVerificationRead.model_validate(verification)


@router.post(
    "/field-verifications/{verification_id}/finalize",
    response_model=FieldVerificationRead,
)
def finalize_field_verification(
    verification_id: uuid.UUID,
    payload: FieldVerificationFinalize,
    response: Response,
    session: DatabaseSession,
) -> FieldVerificationRead:
    try:
        verification, finalized = VerificationService(
            session
        ).finalize_field_verification(
            verification_id, not_applicable=payload.not_applicable
        )
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not finalized:
        response.status_code = status.HTTP_200_OK
    return FieldVerificationRead.model_validate(verification)
