import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.confidence import ReviewPriority, RevisionConfidenceAssessment
from app.models.source_registry import constrained_enum


class ReviewRoutingPolicyVersion(enum.StrEnum):
    V1 = "V1"


class ReviewRoutingReasonCode(enum.StrEnum):
    AUTHORITATIVE_CONFLICT = "AUTHORITATIVE_CONFLICT"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    INSUFFICIENT_CRITICAL_EVIDENCE = "INSUFFICIENT_CRITICAL_EVIDENCE"
    PARTIAL_VERIFICATION = "PARTIAL_VERIFICATION"
    AMBIGUOUS_POST_SPLIT = "AMBIGUOUS_POST_SPLIT"
    AMBIGUOUS_POST_DETAILS = "AMBIGUOUS_POST_DETAILS"
    UNCLEAR_CRITICAL_MEANING = "UNCLEAR_CRITICAL_MEANING"
    UNCERTAIN_VACANCY_MAPPING = "UNCERTAIN_VACANCY_MAPPING"
    POSSIBLE_WRONG_POST_OWNERSHIP = "POSSIBLE_WRONG_POST_OWNERSHIP"


class ReviewRoutingAssessment(Base):
    """Immutable routing decision derived from, but not embedded in, Confidence V2."""

    __tablename__ = "review_routing_assessments"
    __table_args__ = (
        UniqueConstraint(
            "revision_confidence_assessment_id",
            "policy_version",
            name="uq_review_routing_confidence_policy",
        ),
        CheckConstraint(
            "length(input_hash) = 64 AND input_hash = lower(input_hash)",
            name="ck_review_routing_input_hash_format",
        ),
        CheckConstraint(
            "(review_required AND priority <> 'NONE') OR "
            "(NOT review_required AND priority = 'NONE')",
            name="ck_review_routing_required_priority",
        ),
        Index("ix_review_routing_candidate_revision", "candidate_revision_id"),
        Index("ix_review_routing_verification_run", "verification_run_id"),
        Index("ix_review_routing_queue", "review_required", "priority"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    revision_confidence_assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("revision_confidence_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    verification_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_candidate_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    policy_version: Mapped[ReviewRoutingPolicyVersion] = mapped_column(
        constrained_enum(ReviewRoutingPolicyVersion, "ck_review_routing_policy_version"),
        nullable=False,
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    priority: Mapped[ReviewPriority] = mapped_column(
        constrained_enum(ReviewPriority, "ck_review_routing_priority"), nullable=False
    )
    reason_codes: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    field_routes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    component_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    revision_confidence_assessment: Mapped[RevisionConfidenceAssessment] = relationship()
