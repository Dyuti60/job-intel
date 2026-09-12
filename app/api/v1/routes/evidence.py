import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.evidence import EvidenceType
from app.schemas.evidence import (
    CandidateFieldEvidenceRead,
    EvidenceCreate,
    EvidenceRead,
)
from app.services.evidence import EvidenceService
from app.services.exceptions import DomainConflictError, ResourceNotFoundError

router = APIRouter(tags=["candidate evidence"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def raise_http_error(error: ResourceNotFoundError | DomainConflictError) -> None:
    error_status = (
        status.HTTP_404_NOT_FOUND
        if isinstance(error, ResourceNotFoundError)
        else status.HTTP_409_CONFLICT
    )
    raise HTTPException(status_code=error_status, detail=str(error)) from error


@router.post(
    "/evidence",
    response_model=EvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_evidence(
    payload: EvidenceCreate,
    response: Response,
    session: DatabaseSession,
) -> EvidenceRead:
    try:
        evidence, created = EvidenceService(session).create_evidence(payload)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not created:
        response.status_code = status.HTTP_200_OK
    return EvidenceRead.model_validate(evidence)


@router.get("/evidence", response_model=list[EvidenceRead])
def list_evidence(
    session: DatabaseSession,
    source_document_id: uuid.UUID | None = None,
    evidence_type: EvidenceType | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[EvidenceRead]:
    evidence = EvidenceService(session).list_evidence(
        source_document_id=source_document_id,
        evidence_type=evidence_type,
        offset=offset,
        limit=limit,
    )
    return [EvidenceRead.model_validate(item) for item in evidence]


@router.get("/evidence/{evidence_id}", response_model=EvidenceRead)
def get_evidence(evidence_id: uuid.UUID, session: DatabaseSession) -> EvidenceRead:
    try:
        evidence = EvidenceService(session).get_evidence(evidence_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return EvidenceRead.model_validate(evidence)


@router.post(
    "/candidate-fields/{field_id}/evidence/{evidence_id}",
    response_model=CandidateFieldEvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def link_evidence(
    field_id: uuid.UUID,
    evidence_id: uuid.UUID,
    response: Response,
    session: DatabaseSession,
) -> CandidateFieldEvidenceRead:
    try:
        link, created = EvidenceService(session).link_evidence(field_id, evidence_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    if not created:
        response.status_code = status.HTTP_200_OK
    return CandidateFieldEvidenceRead.model_validate(link)


@router.get(
    "/candidate-fields/{field_id}/evidence",
    response_model=list[EvidenceRead],
)
def list_field_evidence(
    field_id: uuid.UUID, session: DatabaseSession
) -> list[EvidenceRead]:
    try:
        evidence = EvidenceService(session).list_field_evidence(field_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        raise_http_error(error)
    return [EvidenceRead.model_validate(item) for item in evidence]
