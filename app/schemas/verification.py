import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.candidates import CandidateValueType
from app.models.source_registry import SourceClass
from app.models.verification import (
    EvidenceAssessmentType,
    FieldVerificationOutcome,
    FieldVerificationStatus,
    VerificationReasonCode,
    VerificationRunStatus,
    VerificationTriggerType,
)
from app.services.candidate_values import normalize_typed_value


class VerificationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class VerificationRunCreate(VerificationSchema):
    candidate_revision_id: uuid.UUID
    trigger_type: VerificationTriggerType = VerificationTriggerType.MANUAL


class VerificationRunComplete(VerificationSchema):
    status: VerificationRunStatus
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=4000)

    @field_validator("error_code", "error_message")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_terminal_status(self) -> "VerificationRunComplete":
        terminal = {
            VerificationRunStatus.COMPLETED,
            VerificationRunStatus.PARTIAL,
            VerificationRunStatus.FAILED,
        }
        if self.status not in terminal:
            raise ValueError("status must be COMPLETED, PARTIAL, or FAILED")
        return self


class VerificationRunRead(VerificationSchema):
    id: uuid.UUID
    candidate_revision_id: uuid.UUID
    candidate_revision_hash_snapshot: str
    status: VerificationRunStatus
    trigger_type: VerificationTriggerType
    started_at: datetime | None
    completed_at: datetime | None
    fields_total: int
    fields_confirmed: int
    fields_conflicted: int
    fields_insufficient: int
    fields_not_applicable: int
    error_code: str | None
    error_message: str | None
    created_at: datetime


class VerificationEvidenceAssessmentCreate(VerificationSchema):
    evidence_id: uuid.UUID
    assessment: EvidenceAssessmentType
    asserted_value: Any = None
    asserted_value_type: CandidateValueType | None = None
    assessment_note: str | None = Field(default=None, max_length=4000)

    @field_validator("assessment_note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def normalize_asserted_value(self) -> "VerificationEvidenceAssessmentCreate":
        if self.asserted_value_type is None:
            if self.asserted_value is not None:
                raise ValueError("asserted_value_type is required with asserted_value")
            return self
        try:
            self.asserted_value = normalize_typed_value(
                self.asserted_value_type, self.asserted_value
            )
        except ValueError as error:
            raise ValueError(str(error)) from error
        return self


class VerificationEvidenceAssessmentRead(VerificationSchema):
    id: uuid.UUID
    field_verification_id: uuid.UUID
    evidence_id: uuid.UUID
    source_document_id: uuid.UUID
    source_endpoint_id: uuid.UUID
    source_class: SourceClass
    assessment: EvidenceAssessmentType
    asserted_value: Any
    asserted_value_type: CandidateValueType | None
    assessment_note: str | None
    evidence_excerpt: str
    evidence_source_locator: str | None
    created_at: datetime


class FieldVerificationFinalize(VerificationSchema):
    not_applicable: bool = False


class FieldVerificationRead(VerificationSchema):
    id: uuid.UUID
    verification_run_id: uuid.UUID
    candidate_field_id: uuid.UUID
    candidate_field_path_snapshot: str
    candidate_field_value_snapshot: Any
    candidate_field_type_snapshot: CandidateValueType
    status: FieldVerificationStatus
    outcome: FieldVerificationOutcome | None
    reason_code: VerificationReasonCode | None
    finding_summary: str | None
    authoritative_support_count: int
    official_support_count: int
    secondary_support_count: int
    authoritative_conflict_count: int
    official_conflict_count: int
    secondary_conflict_count: int
    evidence_count: int
    finalized_at: datetime | None
    created_at: datetime
    assessments: list[VerificationEvidenceAssessmentRead]
