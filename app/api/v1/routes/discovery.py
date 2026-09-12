import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.discovery import (
    DiscoveryRunStatus,
    DiscoveryTriggerType,
    DocumentType,
    SourceDocumentStatus,
)
from app.schemas.discovery import (
    DiscoveryObservationRead,
    DiscoveryRunComplete,
    DiscoveryRunCreate,
    DiscoveryRunRead,
    DocumentObservationCreate,
    DocumentObservationResult,
    SourceDocumentRead,
)
from app.schemas.source_registry import RegistryHttpUrl
from app.services.discovery import DiscoveryService
from app.services.exceptions import (
    DomainConflictError,
    DuplicateResourceError,
    ResourceNotFoundError,
)

router = APIRouter(tags=["discovery provenance"])
DatabaseSession = Annotated[Session, Depends(get_db)]
DiscoveryError = ResourceNotFoundError | DuplicateResourceError | DomainConflictError


def raise_http_error(error: DiscoveryError) -> None:
    if isinstance(error, ResourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/discovery-runs",
    response_model=DiscoveryRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_run(payload: DiscoveryRunCreate, session: DatabaseSession) -> DiscoveryRunRead:
    try:
        run = DiscoveryService(session).create_run(
            payload.source_endpoint_id, payload.trigger_type
        )
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return DiscoveryRunRead.model_validate(run)


@router.get("/discovery-runs", response_model=list[DiscoveryRunRead])
def list_runs(
    session: DatabaseSession,
    source_endpoint_id: uuid.UUID | None = None,
    status_filter: Annotated[DiscoveryRunStatus | None, Query(alias="status")] = None,
    trigger_type: DiscoveryTriggerType | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[DiscoveryRunRead]:
    runs = DiscoveryService(session).list_runs(
        source_endpoint_id=source_endpoint_id,
        status=status_filter,
        trigger_type=trigger_type,
        offset=offset,
        limit=limit,
    )
    return [DiscoveryRunRead.model_validate(run) for run in runs]


@router.get("/discovery-runs/{run_id}", response_model=DiscoveryRunRead)
def get_run(run_id: uuid.UUID, session: DatabaseSession) -> DiscoveryRunRead:
    try:
        run = DiscoveryService(session).get_run(run_id)
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return DiscoveryRunRead.model_validate(run)


@router.post("/discovery-runs/{run_id}/complete", response_model=DiscoveryRunRead)
def complete_run(
    run_id: uuid.UUID,
    payload: DiscoveryRunComplete,
    session: DatabaseSession,
) -> DiscoveryRunRead:
    try:
        run = DiscoveryService(session).complete_run(run_id, payload)
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return DiscoveryRunRead.model_validate(run)


@router.post(
    "/discovery-runs/{run_id}/documents",
    response_model=DocumentObservationResult,
    status_code=status.HTTP_201_CREATED,
)
def record_document(
    run_id: uuid.UUID,
    payload: DocumentObservationCreate,
    session: DatabaseSession,
) -> DocumentObservationResult:
    try:
        classification, document, observation = DiscoveryService(session).record_document(
            run_id, payload
        )
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return DocumentObservationResult(
        classification=classification,
        document=SourceDocumentRead.model_validate(document),
        observation=DiscoveryObservationRead.model_validate(observation),
    )


@router.get(
    "/discovery-runs/{run_id}/documents",
    response_model=list[DiscoveryObservationRead],
)
def list_run_documents(
    run_id: uuid.UUID, session: DatabaseSession
) -> list[DiscoveryObservationRead]:
    try:
        observations = DiscoveryService(session).list_run_observations(run_id)
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return [DiscoveryObservationRead.model_validate(item) for item in observations]


@router.get("/source-documents", response_model=list[SourceDocumentRead])
def list_documents(
    session: DatabaseSession,
    source_endpoint_id: uuid.UUID | None = None,
    normalized_document_url: RegistryHttpUrl | None = None,
    document_type: DocumentType | None = None,
    status_filter: Annotated[SourceDocumentStatus | None, Query(alias="status")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SourceDocumentRead]:
    documents = DiscoveryService(session).list_documents(
        source_endpoint_id=source_endpoint_id,
        normalized_document_url=(
            str(normalized_document_url) if normalized_document_url is not None else None
        ),
        document_type=document_type,
        status=status_filter,
        offset=offset,
        limit=limit,
    )
    return [SourceDocumentRead.model_validate(item) for item in documents]


@router.get("/source-documents/{document_id}", response_model=SourceDocumentRead)
def get_document(
    document_id: uuid.UUID, session: DatabaseSession
) -> SourceDocumentRead:
    try:
        document = DiscoveryService(session).get_document(document_id)
    except (ResourceNotFoundError, DuplicateResourceError, DomainConflictError) as error:
        raise_http_error(error)
    return SourceDocumentRead.model_validate(document)
