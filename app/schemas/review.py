import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.candidates import CandidateValueType
from app.models.confidence import ConfidencePolicyVersion, ReviewPriority, ReviewReasonCode
from app.models.review import (
    ReviewCaseOutcome,
    ReviewCaseStatus,
    ReviewDecisionType,
    ReviewItemScope,
    ReviewItemStatus,
)


class ReviewSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ReviewCaseCreate(ReviewSchema):
    revision_confidence_assessment_id: uuid.UUID


class ReviewDecisionCreate(ReviewSchema):
    decision: ReviewDecisionType
    reviewer_identifier: str = Field(min_length=1, max_length=255)
    decision_note: str | None = Field(default=None, max_length=8000)
    corrected_value_type: CandidateValueType | None = None
    corrected_value: Any = None
    evidence_note: str | None = Field(default=None, max_length=4000)

    @field_validator("reviewer_identifier")
    @classmethod
    def normalize_reviewer(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reviewer_identifier must not be blank")
        return normalized

    @field_validator("decision_note", "evidence_note")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_decision_shape(self) -> "ReviewDecisionCreate":
        if self.decision == ReviewDecisionType.CORRECT_AND_APPROVE:
            if self.corrected_value_type is None:
                raise ValueError("corrected_value_type is required for CORRECT_AND_APPROVE")
        elif self.corrected_value_type is not None or self.corrected_value is not None:
            raise ValueError("corrected values are allowed only for CORRECT_AND_APPROVE")
        if self.decision != ReviewDecisionType.APPROVE_AS_IS and self.decision_note is None:
            raise ValueError(f"decision_note is required for {self.decision.value}")
        return self


class ReviewDecisionRead(ReviewSchema):
    id: uuid.UUID
    review_item_id: uuid.UUID
    decision: ReviewDecisionType
    reviewer_identifier: str
    decision_note: str | None
    original_value_snapshot: Any
    original_value_type_snapshot: CandidateValueType | None
    corrected_value_type: CandidateValueType | None
    corrected_value: Any
    evidence_note: str | None
    decided_at: datetime
    created_at: datetime


class ReviewItemRead(ReviewSchema):
    id: uuid.UUID
    review_case_id: uuid.UUID
    scope: ReviewItemScope
    field_confidence_assessment_id: uuid.UUID | None
    field_verification_id: uuid.UUID | None
    candidate_field_id: uuid.UUID | None
    status: ReviewItemStatus
    priority: ReviewPriority
    policy_version: ConfidencePolicyVersion
    field_path_snapshot: str | None
    candidate_value_type_snapshot: CandidateValueType | None
    candidate_value_snapshot: Any
    confidence_score_snapshot: int | None
    review_reason_codes_snapshot: list[ReviewReasonCode]
    component_breakdown_snapshot: dict[str, Any]
    created_at: datetime
    resolved_at: datetime | None
    decision: ReviewDecisionRead | None


class ReviewCaseSummary(ReviewSchema):
    id: uuid.UUID
    candidate_revision_id: uuid.UUID
    verification_run_id: uuid.UUID
    revision_confidence_assessment_id: uuid.UUID
    status: ReviewCaseStatus
    priority: ReviewPriority
    policy_version: ConfidencePolicyVersion
    revision_score_snapshot: int | None
    revision_review_reason_codes_snapshot: list[ReviewReasonCode]
    component_breakdown_snapshot: dict[str, Any]
    outcome: ReviewCaseOutcome | None
    opened_at: datetime
    started_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReviewCaseDetail(ReviewCaseSummary):
    items: list[ReviewItemRead]


class ApprovedProjectionField(ReviewSchema):
    candidate_field_id: uuid.UUID
    field_path: str
    value_type: CandidateValueType
    original_value: Any
    effective_value: Any
    approved: bool
    corrected: bool
    review_decision_id: uuid.UUID | None


class ApprovedProjectionRead(ReviewSchema):
    review_case_id: uuid.UUID
    candidate_revision_id: uuid.UUID
    outcome: ReviewCaseOutcome
    master_eligible: bool
    fields: list[ApprovedProjectionField]
