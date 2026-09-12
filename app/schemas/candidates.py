import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.candidates import CandidateStatus, CandidateValueType
from app.services.candidate_values import normalize_typed_value


class CandidateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RecruitmentCandidateCreate(CandidateSchema):
    recruiting_authority_id: uuid.UUID
    candidate_key: str = Field(
        min_length=2,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    display_name: str = Field(min_length=1, max_length=500)

    @field_validator("candidate_key", mode="before")
    @classmethod
    def normalize_candidate_key(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("display_name must not be blank")
        return normalized


class RecruitmentCandidateUpdate(CandidateSchema):
    status: CandidateStatus


class RecruitmentCandidateRead(CandidateSchema):
    id: uuid.UUID
    recruiting_authority_id: uuid.UUID
    candidate_key: str
    display_name: str
    status: CandidateStatus
    revision_count: int
    latest_revision_number: int | None
    created_at: datetime
    updated_at: datetime


class CandidateFieldCreate(CandidateSchema):
    field_path: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[a-z][a-z0-9_]*(?:\.(?:[a-z][a-z0-9_]*|[0-9]+))*$",
    )
    value_type: CandidateValueType
    value: Any = None
    raw_value: str | None = Field(default=None, max_length=10_000)
    source_locator: str | None = Field(default=None, max_length=1024)

    @field_validator("field_path")
    @classmethod
    def strip_field_path(cls, value: str) -> str:
        return value.strip()

    @field_validator("source_locator")
    @classmethod
    def strip_locator(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def normalize_value(self) -> "CandidateFieldCreate":
        try:
            self.value = normalize_typed_value(self.value_type, self.value)
        except ValueError as error:
            raise ValueError(str(error)) from error
        return self


class RecruitmentCandidateRevisionCreate(CandidateSchema):
    source_document_id: uuid.UUID
    fields: list[CandidateFieldCreate] = Field(min_length=1, max_length=500)
    extraction_method: str | None = Field(default=None, min_length=1, max_length=128)
    extraction_note: str | None = Field(default=None, max_length=4000)

    @field_validator("extraction_method", "extraction_note")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def unique_field_paths(self) -> "RecruitmentCandidateRevisionCreate":
        paths = [field.field_path for field in self.fields]
        if len(paths) != len(set(paths)):
            raise ValueError("field_path values must be unique within a revision")
        return self


class CandidateFieldRead(CandidateSchema):
    id: uuid.UUID
    candidate_revision_id: uuid.UUID
    source_document_id: uuid.UUID
    field_path: str
    value_type: CandidateValueType
    value: Any
    raw_value: str | None
    source_locator: str | None
    created_at: datetime


class RecruitmentCandidateRevisionRead(CandidateSchema):
    id: uuid.UUID
    recruitment_candidate_id: uuid.UUID
    source_document_id: uuid.UUID
    revision_number: int
    revision_hash: str
    extraction_method: str | None
    extraction_note: str | None
    created_at: datetime
    fields: list[CandidateFieldRead]
