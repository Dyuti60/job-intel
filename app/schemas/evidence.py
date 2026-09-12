import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.evidence import EvidenceType
from app.services.evidence_values import (
    EVIDENCE_CONTEXT_MAX_LENGTH,
    EVIDENCE_EXCERPT_MAX_LENGTH,
    EVIDENCE_LOCATOR_MAX_LENGTH,
    normalize_evidence_text,
    normalize_optional_evidence_text,
    normalize_source_locator,
)


class EvidenceSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EvidenceCreate(EvidenceSchema):
    source_document_id: uuid.UUID
    evidence_type: EvidenceType
    source_locator: str | None = Field(
        default=None, max_length=EVIDENCE_LOCATOR_MAX_LENGTH
    )
    excerpt: str = Field(min_length=1, max_length=EVIDENCE_EXCERPT_MAX_LENGTH)
    context: str | None = Field(default=None, max_length=EVIDENCE_CONTEXT_MAX_LENGTH)

    @field_validator("excerpt")
    @classmethod
    def normalize_excerpt(cls, value: str) -> str:
        return normalize_evidence_text(value)

    @field_validator("context")
    @classmethod
    def normalize_context(cls, value: str | None) -> str | None:
        return normalize_optional_evidence_text(value)

    @field_validator("source_locator")
    @classmethod
    def normalize_locator(cls, value: str | None) -> str | None:
        return normalize_source_locator(value)

    @model_validator(mode="after")
    def require_excerpt_content(self) -> "EvidenceCreate":
        if not self.excerpt:
            raise ValueError("excerpt must not be blank")
        return self


class EvidenceRead(EvidenceSchema):
    id: uuid.UUID
    source_document_id: uuid.UUID
    evidence_type: EvidenceType
    source_locator: str | None
    excerpt: str
    context: str | None
    evidence_hash: str
    created_at: datetime


class CandidateFieldEvidenceRead(EvidenceSchema):
    id: uuid.UUID
    candidate_field_id: uuid.UUID
    evidence_id: uuid.UUID
    source_document_id: uuid.UUID
    created_at: datetime
