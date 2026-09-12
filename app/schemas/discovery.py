import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from app.models.discovery import (
    DiscoveryRunStatus,
    DiscoveryTriggerType,
    DocumentType,
    ObservationStatus,
    SourceDocumentStatus,
)
from app.schemas.source_registry import RegistryHttpUrl


class DiscoverySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DiscoveryRunCreate(DiscoverySchema):
    source_endpoint_id: uuid.UUID
    trigger_type: DiscoveryTriggerType = DiscoveryTriggerType.MANUAL


class DiscoveryRunRead(DiscoverySchema):
    id: uuid.UUID
    source_endpoint_id: uuid.UUID
    status: DiscoveryRunStatus
    started_at: datetime
    completed_at: datetime | None
    trigger_type: DiscoveryTriggerType
    documents_discovered: int
    documents_new: int
    documents_changed: int
    documents_unchanged: int
    error_code: str | None
    error_message: str | None
    created_at: datetime


class CompletionStatus(enum.StrEnum):
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DiscoveryRunComplete(DiscoverySchema):
    status: CompletionStatus
    error_code: str | None = Field(default=None, min_length=1, max_length=128)
    error_message: str | None = Field(default=None, min_length=1, max_length=4000)

    @field_validator("error_code", "error_message")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def successful_run_has_no_error(self) -> "DiscoveryRunComplete":
        if self.status == CompletionStatus.SUCCEEDED and (
            self.error_code is not None or self.error_message is not None
        ):
            raise ValueError("a successful run cannot include failure details")
        return self


class DocumentObservationCreate(DiscoverySchema):
    document_url: str = Field(min_length=1, max_length=2048)
    document_type: DocumentType
    content_type: str | None = Field(default=None, min_length=1, max_length=255)
    content_text: str | None = Field(default=None, max_length=65_536)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    content_length: int | None = Field(default=None, ge=0)
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    http_etag: str | None = Field(default=None, min_length=1, max_length=512)
    http_last_modified: str | None = Field(default=None, min_length=1, max_length=255)
    retrieved_at: datetime | None = None
    storage_uri: str | None = Field(default=None, min_length=1, max_length=2048)

    @field_validator(
        "content_type",
        "http_etag",
        "http_last_modified",
        "storage_uri",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("document_url")
    @classmethod
    def validate_document_url(cls, value: str) -> str:
        TypeAdapter(RegistryHttpUrl).validate_python(value)
        return value.strip()

    @field_validator("content_hash")
    @classmethod
    def canonicalize_hash(cls, value: str | None) -> str | None:
        return value.lower() if value is not None else None

    @field_validator("retrieved_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_content_identity(self) -> "DocumentObservationCreate":
        supplied = (self.content_text is not None) + (self.content_hash is not None)
        if supplied != 1:
            raise ValueError("provide exactly one of content_text or content_hash")
        if self.content_text is not None:
            byte_length = len(self.content_text.encode("utf-8"))
            if self.content_length is not None and self.content_length != byte_length:
                raise ValueError("content_length does not match UTF-8 content_text bytes")
        return self


class SourceDocumentRead(DiscoverySchema):
    id: uuid.UUID
    source_endpoint_id: uuid.UUID
    first_discovery_run_id: uuid.UUID
    latest_discovery_run_id: uuid.UUID
    document_url: str
    normalized_document_url: RegistryHttpUrl
    document_type: DocumentType
    content_type: str | None
    content_hash: str
    content_length: int | None
    http_etag: str | None
    http_last_modified: str | None
    storage_uri: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    retrieved_at: datetime
    status: SourceDocumentStatus
    created_at: datetime
    updated_at: datetime


class DiscoveryObservationRead(DiscoverySchema):
    id: uuid.UUID
    discovery_run_id: uuid.UUID
    source_document_id: uuid.UUID
    observation_status: ObservationStatus
    observed_url: str
    observed_at: datetime
    retrieved_at: datetime
    http_status_code: int | None
    content_type: str | None
    content_length: int | None
    http_etag: str | None
    http_last_modified: str | None
    created_at: datetime


class DocumentObservationResult(DiscoverySchema):
    classification: ObservationStatus
    document: SourceDocumentRead
    observation: DiscoveryObservationRead
