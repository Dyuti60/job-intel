import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.discovery import (
    DiscoveryObservation,
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoveryTriggerType,
    DocumentType,
    ObservationStatus,
    SourceDocument,
    SourceDocumentStatus,
)
from app.models.source_registry import AuthorityStatus, SourceStatus
from app.repositories.discovery import (
    DiscoveryObservationRepository,
    DiscoveryRunRepository,
    SourceDocumentRepository,
)
from app.repositories.source_registry import SourceEndpointRepository
from app.schemas.discovery import (
    DiscoveryRunComplete,
    DocumentObservationCreate,
)
from app.services.exceptions import (
    DomainConflictError,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from app.services.url_normalization import normalize_http_url


class DiscoveryService:
    def __init__(self, session: Session, *, commit: bool = True) -> None:
        self.session = session
        self.commit = commit
        self.endpoints = SourceEndpointRepository(session)
        self.runs = DiscoveryRunRepository(session)
        self.documents = SourceDocumentRepository(session)
        self.observations = DiscoveryObservationRepository(session)

    def create_run(
        self, source_endpoint_id: uuid.UUID, trigger_type: DiscoveryTriggerType
    ) -> DiscoveryRun:
        endpoint = self.endpoints.get(source_endpoint_id)
        if endpoint is None:
            raise ResourceNotFoundError("Source endpoint not found")
        if endpoint.recruiting_authority.status != AuthorityStatus.ACTIVE:
            raise DomainConflictError("Recruiting authority is not active")
        if endpoint.status != SourceStatus.ACTIVE:
            raise DomainConflictError("Source endpoint is not active")
        if not endpoint.discovery_enabled:
            raise DomainConflictError("Discovery is disabled for this source endpoint")

        run = DiscoveryRun(
            source_endpoint_id=source_endpoint_id,
            status=DiscoveryRunStatus.RUNNING,
            started_at=datetime.now(UTC),
            trigger_type=trigger_type,
            documents_discovered=0,
            documents_new=0,
            documents_changed=0,
            documents_unchanged=0,
        )
        self.runs.add(run)
        self._save()
        self.session.refresh(run)
        return run

    def get_run(self, run_id: uuid.UUID) -> DiscoveryRun:
        if (run := self.runs.get(run_id)) is None:
            raise ResourceNotFoundError("Discovery run not found")
        return run

    def list_runs(
        self,
        *,
        source_endpoint_id: uuid.UUID | None,
        status: DiscoveryRunStatus | None,
        trigger_type: DiscoveryTriggerType | None,
        offset: int,
        limit: int,
    ) -> list[DiscoveryRun]:
        return self.runs.list(
            source_endpoint_id=source_endpoint_id,
            status=status,
            trigger_type=trigger_type,
            offset=offset,
            limit=limit,
        )

    def complete_run(
        self, run_id: uuid.UUID, data: DiscoveryRunComplete
    ) -> DiscoveryRun:
        run = self.get_run(run_id)
        if run.status != DiscoveryRunStatus.RUNNING:
            raise DomainConflictError(
                f"Cannot complete a discovery run in {run.status.value} status"
            )

        run.status = DiscoveryRunStatus(data.status.value)
        run.completed_at = datetime.now(UTC)
        run.error_code = data.error_code
        run.error_message = data.error_message
        self._save()
        self.session.refresh(run)
        return run

    def record_document(
        self, run_id: uuid.UUID, data: DocumentObservationCreate
    ) -> tuple[ObservationStatus, SourceDocument, DiscoveryObservation]:
        run = self.get_run(run_id)
        if run.status != DiscoveryRunStatus.RUNNING:
            raise DomainConflictError(
                f"Cannot record documents for a run in {run.status.value} status"
            )

        normalized_url = normalize_http_url(data.document_url)
        content_hash, content_length = self._content_identity(data)
        retrieved_at = data.retrieved_at or datetime.now(UTC)
        observed_at = datetime.now(UTC)
        document = self.documents.get_by_identity(
            source_endpoint_id=run.source_endpoint_id,
            normalized_document_url=normalized_url,
            content_hash=content_hash,
        )

        if document is not None:
            existing_observation = self.observations.get_for_run_document(run.id, document.id)
            if existing_observation is not None:
                return existing_observation.observation_status, document, existing_observation
            classification = ObservationStatus.UNCHANGED
            document.latest_discovery_run_id = run.id
            document.last_seen_at = observed_at
            document.status = SourceDocumentStatus.ACTIVE
            if document.storage_uri is None and data.storage_uri is not None:
                document.storage_uri = data.storage_uri
        else:
            classification = (
                ObservationStatus.CHANGED
                if self.documents.has_url(
                    source_endpoint_id=run.source_endpoint_id,
                    normalized_document_url=normalized_url,
                )
                else ObservationStatus.NEW
            )
            document = SourceDocument(
                source_endpoint_id=run.source_endpoint_id,
                first_discovery_run_id=run.id,
                latest_discovery_run_id=run.id,
                document_url=str(data.document_url),
                normalized_document_url=normalized_url,
                document_type=data.document_type,
                content_type=data.content_type,
                content_hash=content_hash,
                content_length=content_length,
                http_etag=data.http_etag,
                http_last_modified=data.http_last_modified,
                storage_uri=data.storage_uri,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
                retrieved_at=retrieved_at,
                status=SourceDocumentStatus.ACTIVE,
            )
            self.documents.add(document)
            self.session.flush()

        observation = DiscoveryObservation(
            discovery_run_id=run.id,
            source_document_id=document.id,
            observation_status=classification,
            observed_url=str(data.document_url),
            observed_at=observed_at,
            retrieved_at=retrieved_at,
            http_status_code=data.http_status_code,
            content_type=data.content_type,
            content_length=content_length,
            http_etag=data.http_etag,
            http_last_modified=data.http_last_modified,
        )
        self.observations.add(observation)
        self._increment_counters(run, classification)
        try:
            self._save()
        except IntegrityError as error:
            self.session.rollback()
            raise DuplicateResourceError(
                "The document observation conflicts with an existing record"
            ) from error
        self.session.refresh(document)
        self.session.refresh(observation)
        return classification, document, observation

    def list_run_observations(self, run_id: uuid.UUID) -> list[DiscoveryObservation]:
        self.get_run(run_id)
        return self.observations.list_for_run(run_id)

    def get_document(self, document_id: uuid.UUID) -> SourceDocument:
        if (document := self.documents.get(document_id)) is None:
            raise ResourceNotFoundError("Source document not found")
        return document

    def list_documents(
        self,
        *,
        source_endpoint_id: uuid.UUID | None,
        normalized_document_url: str | None,
        document_type: DocumentType | None,
        status: SourceDocumentStatus | None,
        offset: int,
        limit: int,
    ) -> list[SourceDocument]:
        normalized_url = (
            normalize_http_url(normalized_document_url)
            if normalized_document_url is not None
            else None
        )
        return self.documents.list(
            source_endpoint_id=source_endpoint_id,
            normalized_document_url=normalized_url,
            document_type=document_type,
            status=status,
            offset=offset,
            limit=limit,
        )

    @staticmethod
    def _content_identity(data: DocumentObservationCreate) -> tuple[str, int | None]:
        if data.content_text is not None:
            content = data.content_text.encode("utf-8")
            return hashlib.sha256(content).hexdigest(), len(content)
        return data.content_hash or "", data.content_length

    @staticmethod
    def _increment_counters(run: DiscoveryRun, classification: ObservationStatus) -> None:
        run.documents_discovered += 1
        if classification == ObservationStatus.NEW:
            run.documents_new += 1
        elif classification == ObservationStatus.CHANGED:
            run.documents_changed += 1
        elif classification == ObservationStatus.UNCHANGED:
            run.documents_unchanged += 1

    def _save(self) -> None:
        self.session.commit() if self.commit else self.session.flush()
