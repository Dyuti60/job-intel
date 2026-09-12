import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.source_registry import constrained_enum

if TYPE_CHECKING:
    from app.models.source_registry import SourceEndpoint


class DiscoveryRunStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DiscoveryTriggerType(enum.StrEnum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"
    RETRY = "RETRY"


class DocumentType(enum.StrEnum):
    HTML = "HTML"
    PDF = "PDF"
    JSON = "JSON"
    OTHER = "OTHER"


class SourceDocumentStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class ObservationStatus(enum.StrEnum):
    NEW = "NEW"
    UNCHANGED = "UNCHANGED"
    CHANGED = "CHANGED"
    UNAVAILABLE = "UNAVAILABLE"


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "documents_discovered >= 0 AND documents_new >= 0 "
            "AND documents_changed >= 0 AND documents_unchanged >= 0",
            name="ck_discovery_runs_nonnegative_counters",
        ),
        CheckConstraint(
            "(status IN ('PENDING', 'RUNNING') AND completed_at IS NULL) "
            "OR (status IN ('SUCCEEDED', 'PARTIAL', 'FAILED') AND completed_at IS NOT NULL)",
            name="ck_discovery_runs_completion_time",
        ),
        Index("ix_discovery_runs_source_endpoint_id", "source_endpoint_id"),
        Index("ix_discovery_runs_status", "status"),
        Index("ix_discovery_runs_started_at", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_endpoints.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[DiscoveryRunStatus] = mapped_column(
        constrained_enum(DiscoveryRunStatus, "ck_discovery_runs_status"),
        nullable=False,
        default=DiscoveryRunStatus.RUNNING,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger_type: Mapped[DiscoveryTriggerType] = mapped_column(
        constrained_enum(DiscoveryTriggerType, "ck_discovery_runs_trigger_type"),
        nullable=False,
    )
    documents_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source_endpoint: Mapped["SourceEndpoint"] = relationship(back_populates="discovery_runs")
    observations: Mapped[list["DiscoveryObservation"]] = relationship(
        back_populates="discovery_run"
    )


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint(
            "source_endpoint_id",
            "normalized_document_url",
            "content_hash",
            name="uq_source_documents_version_identity",
        ),
        CheckConstraint(
            "content_length IS NULL OR content_length >= 0",
            name="ck_source_documents_nonnegative_length",
        ),
        Index("ix_source_documents_normalized_url", "normalized_document_url"),
        Index("ix_source_documents_content_hash", "content_hash"),
        Index("ix_source_documents_document_type", "document_type"),
        Index("ix_source_documents_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_endpoints.id", ondelete="RESTRICT"),
        nullable=False,
    )
    first_discovery_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    latest_discovery_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_document_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(
        constrained_enum(DocumentType, "ck_source_documents_type"),
        nullable=False,
    )
    content_type: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_length: Mapped[int | None] = mapped_column(Integer)
    http_etag: Mapped[str | None] = mapped_column(String(512))
    http_last_modified: Mapped[str | None] = mapped_column(String(255))
    storage_uri: Mapped[str | None] = mapped_column(String(2048))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[SourceDocumentStatus] = mapped_column(
        constrained_enum(SourceDocumentStatus, "ck_source_documents_status"),
        nullable=False,
        default=SourceDocumentStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    source_endpoint: Mapped["SourceEndpoint"] = relationship(back_populates="source_documents")
    observations: Mapped[list["DiscoveryObservation"]] = relationship(
        back_populates="source_document"
    )


class DiscoveryObservation(Base):
    __tablename__ = "discovery_observations"
    __table_args__ = (
        UniqueConstraint(
            "discovery_run_id",
            "source_document_id",
            name="uq_discovery_observations_run_document",
        ),
        CheckConstraint(
            "http_status_code IS NULL OR "
            "(http_status_code >= 100 AND http_status_code <= 599)",
            name="ck_discovery_observations_http_status",
        ),
        CheckConstraint(
            "content_length IS NULL OR content_length >= 0",
            name="ck_discovery_observations_nonnegative_length",
        ),
        Index("ix_discovery_observations_document_id", "source_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    discovery_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    observation_status: Mapped[ObservationStatus] = mapped_column(
        constrained_enum(ObservationStatus, "ck_discovery_observations_status"),
        nullable=False,
    )
    observed_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    http_status_code: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255))
    content_length: Mapped[int | None] = mapped_column(Integer)
    http_etag: Mapped[str | None] = mapped_column(String(512))
    http_last_modified: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    discovery_run: Mapped[DiscoveryRun] = relationship(back_populates="observations")
    source_document: Mapped[SourceDocument] = relationship(back_populates="observations")
