import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.confidence import (
    ConfidencePolicyVersion,
    FieldCriticality,
    ReviewPriority,
    ReviewReasonCode,
)
from app.models.review_routing import ReviewRoutingPolicyVersion, ReviewRoutingReasonCode


class ConfidenceSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class FieldConfidenceRead(ConfidenceSchema):
    id: uuid.UUID
    field_verification_id: uuid.UUID
    policy_version: ConfidencePolicyVersion
    input_hash: str
    score: int | None
    criticality: FieldCriticality
    review_required: bool
    review_priority: ReviewPriority
    review_reason_codes: list[ReviewReasonCode]
    component_breakdown: dict[str, Any]
    created_at: datetime


class RevisionConfidenceRead(ConfidenceSchema):
    id: uuid.UUID
    verification_run_id: uuid.UUID
    candidate_revision_id: uuid.UUID
    policy_version: ConfidencePolicyVersion
    input_hash: str
    score: int | None
    coverage_ratio: Decimal
    fields_total: int
    fields_scored: int
    fields_not_applicable: int
    critical_fields_total: int
    critical_fields_requiring_review: int
    fields_requiring_review: int
    review_required: bool
    review_priority: ReviewPriority
    review_reason_codes: list[ReviewReasonCode]
    component_breakdown: dict[str, Any]
    created_at: datetime


class RevisionConfidenceDetail(RevisionConfidenceRead):
    field_assessments: list[FieldConfidenceRead]


class ReviewRoutingRead(ConfidenceSchema):
    id: uuid.UUID
    revision_confidence_assessment_id: uuid.UUID
    verification_run_id: uuid.UUID
    candidate_revision_id: uuid.UUID
    policy_version: ReviewRoutingPolicyVersion
    input_hash: str
    review_required: bool
    priority: ReviewPriority
    reason_codes: list[ReviewRoutingReasonCode]
    field_routes: list[dict[str, Any]]
    component_breakdown: dict[str, Any]
    created_at: datetime
