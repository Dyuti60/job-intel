import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.discovery import (
    DiscoveryObservation,
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoveryTriggerType,
    DocumentType,
    SourceDocument,
    SourceDocumentStatus,
)


class DiscoveryRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, run: DiscoveryRun) -> None:
        self.session.add(run)

    def get(self, run_id: uuid.UUID) -> DiscoveryRun | None:
        return self.session.get(DiscoveryRun, run_id)

    def list(
        self,
        *,
        source_endpoint_id: uuid.UUID | None = None,
        status: DiscoveryRunStatus | None = None,
        trigger_type: DiscoveryTriggerType | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[DiscoveryRun]:
        statement: Select[tuple[DiscoveryRun]] = select(DiscoveryRun).order_by(
            DiscoveryRun.started_at.desc(), DiscoveryRun.id
        )
        if source_endpoint_id is not None:
            statement = statement.where(DiscoveryRun.source_endpoint_id == source_endpoint_id)
        if status is not None:
            statement = statement.where(DiscoveryRun.status == status)
        if trigger_type is not None:
            statement = statement.where(DiscoveryRun.trigger_type == trigger_type)
        return list(self.session.scalars(statement.offset(offset).limit(limit)))


class SourceDocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, document: SourceDocument) -> None:
        self.session.add(document)

    def get(self, document_id: uuid.UUID) -> SourceDocument | None:
        return self.session.get(SourceDocument, document_id)

    def get_by_identity(
        self,
        *,
        source_endpoint_id: uuid.UUID,
        normalized_document_url: str,
        content_hash: str,
    ) -> SourceDocument | None:
        return self.session.scalar(
            select(SourceDocument).where(
                SourceDocument.source_endpoint_id == source_endpoint_id,
                SourceDocument.normalized_document_url == normalized_document_url,
                SourceDocument.content_hash == content_hash,
            )
        )

    def has_url(self, *, source_endpoint_id: uuid.UUID, normalized_document_url: str) -> bool:
        return (
            self.session.scalar(
                select(SourceDocument.id)
                .where(
                    SourceDocument.source_endpoint_id == source_endpoint_id,
                    SourceDocument.normalized_document_url == normalized_document_url,
                )
                .limit(1)
            )
            is not None
        )

    def list(
        self,
        *,
        source_endpoint_id: uuid.UUID | None = None,
        normalized_document_url: str | None = None,
        document_type: DocumentType | None = None,
        status: SourceDocumentStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[SourceDocument]:
        statement: Select[tuple[SourceDocument]] = select(SourceDocument).order_by(
            SourceDocument.last_seen_at.desc(), SourceDocument.id
        )
        if source_endpoint_id is not None:
            statement = statement.where(SourceDocument.source_endpoint_id == source_endpoint_id)
        if normalized_document_url is not None:
            statement = statement.where(
                SourceDocument.normalized_document_url == normalized_document_url
            )
        if document_type is not None:
            statement = statement.where(SourceDocument.document_type == document_type)
        if status is not None:
            statement = statement.where(SourceDocument.status == status)
        return list(self.session.scalars(statement.offset(offset).limit(limit)))


class DiscoveryObservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, observation: DiscoveryObservation) -> None:
        self.session.add(observation)

    def get_for_run_document(
        self, run_id: uuid.UUID, document_id: uuid.UUID
    ) -> DiscoveryObservation | None:
        return self.session.scalar(
            select(DiscoveryObservation).where(
                DiscoveryObservation.discovery_run_id == run_id,
                DiscoveryObservation.source_document_id == document_id,
            )
        )

    def list_for_run(self, run_id: uuid.UUID) -> list[DiscoveryObservation]:
        return list(
            self.session.scalars(
                select(DiscoveryObservation)
                .where(DiscoveryObservation.discovery_run_id == run_id)
                .order_by(DiscoveryObservation.observed_at, DiscoveryObservation.id)
            )
        )
