import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.candidates import CandidateField, CandidateValueType
from app.models.confidence import (
    ConfidencePolicyVersion,
    FieldConfidenceAssessment,
    ReviewPriority,
    RevisionConfidenceAssessment,
)
from app.models.review_routing import ReviewRoutingAssessment
from app.models.source_registry import constrained_enum


class ReviewCaseStatus(enum.StrEnum):
    QUEUED = "QUEUED"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class ReviewItemScope(enum.StrEnum):
    FIELD = "FIELD"
    REVISION = "REVISION"


class ReviewItemStatus(enum.StrEnum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


class ReviewDecisionType(enum.StrEnum):
    APPROVE_AS_IS = "APPROVE_AS_IS"
    CORRECT_AND_APPROVE = "CORRECT_AND_APPROVE"
    REJECT = "REJECT"
    REQUEST_REVERIFICATION = "REQUEST_REVERIFICATION"


class ReviewCaseOutcome(enum.StrEnum):
    APPROVED = "APPROVED"
    APPROVED_WITH_CORRECTIONS = "APPROVED_WITH_CORRECTIONS"
    REJECTED = "REJECTED"
    REVERIFICATION_REQUESTED = "REVERIFICATION_REQUESTED"


class ReviewCase(Base):
    __tablename__ = "review_cases"
    __table_args__ = (
        UniqueConstraint(
            "revision_confidence_assessment_id",
            name="uq_review_cases_revision_confidence",
        ),
        UniqueConstraint("review_routing_assessment_id", name="uq_review_cases_review_routing"),
        CheckConstraint(
            "(status = 'QUEUED' AND started_at IS NULL AND resolved_at IS NULL "
            "AND outcome IS NULL) OR "
            "(status = 'IN_REVIEW' AND started_at IS NOT NULL "
            "AND resolved_at IS NULL AND outcome IS NULL) OR "
            "(status = 'RESOLVED' AND started_at IS NOT NULL "
            "AND resolved_at IS NOT NULL AND outcome IS NOT NULL) OR "
            "(status = 'CANCELLED' AND resolved_at IS NOT NULL AND outcome IS NULL)",
            name="ck_review_cases_lifecycle",
        ),
        CheckConstraint(
            "revision_score_snapshot IS NULL OR "
            "(revision_score_snapshot >= 0 AND revision_score_snapshot <= 100)",
            name="ck_review_cases_score_snapshot_range",
        ),
        CheckConstraint(
            "(started_at IS NULL OR started_at >= opened_at) AND "
            "(resolved_at IS NULL OR resolved_at >= opened_at)",
            name="ck_review_cases_timestamp_order",
        ),
        Index("ix_review_cases_candidate_revision_id", "candidate_revision_id"),
        Index("ix_review_cases_verification_run_id", "verification_run_id"),
        Index("ix_review_cases_status_priority", "status", "priority"),
        Index("ix_review_cases_queue_order", "priority", "opened_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_candidate_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    verification_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="RESTRICT"), nullable=False
    )
    revision_confidence_assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("revision_confidence_assessments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_routing_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_routing_assessments.id", ondelete="RESTRICT")
    )
    status: Mapped[ReviewCaseStatus] = mapped_column(
        constrained_enum(ReviewCaseStatus, "ck_review_cases_status"), nullable=False
    )
    priority: Mapped[ReviewPriority] = mapped_column(
        constrained_enum(ReviewPriority, "ck_review_cases_priority"), nullable=False
    )
    policy_version: Mapped[ConfidencePolicyVersion] = mapped_column(
        constrained_enum(ConfidencePolicyVersion, "ck_review_cases_policy_version"),
        nullable=False,
    )
    revision_score_snapshot: Mapped[int | None] = mapped_column(Integer)
    revision_review_reason_codes_snapshot: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    component_breakdown_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    outcome: Mapped[ReviewCaseOutcome | None] = mapped_column(
        constrained_enum(ReviewCaseOutcome, "ck_review_cases_outcome")
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    revision_confidence_assessment: Mapped[RevisionConfidenceAssessment] = relationship()
    review_routing_assessment: Mapped[ReviewRoutingAssessment | None] = relationship()
    items: Mapped[list["ReviewItem"]] = relationship(
        back_populates="review_case", order_by="ReviewItem.created_at"
    )


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("review_case_id", "item_key", name="uq_review_items_case_key"),
        CheckConstraint(
            "(scope = 'FIELD' AND field_confidence_assessment_id IS NOT NULL "
            "AND candidate_field_id IS NOT NULL AND field_path_snapshot IS NOT NULL "
            "AND candidate_value_type_snapshot IS NOT NULL) OR "
            "(scope = 'REVISION' AND field_confidence_assessment_id IS NULL "
            "AND candidate_field_id IS NULL AND field_path_snapshot IS NULL "
            "AND candidate_value_type_snapshot IS NULL "
            "AND candidate_value_snapshot IS NULL)",
            name="ck_review_items_scope_fields",
        ),
        CheckConstraint(
            "(scope = 'REVISION' AND item_key = 'REVISION') OR "
            "(scope = 'FIELD' AND item_key LIKE 'FIELD:%')",
            name="ck_review_items_key_scope",
        ),
        CheckConstraint(
            "confidence_score_snapshot IS NULL OR "
            "(confidence_score_snapshot >= 0 AND confidence_score_snapshot <= 100)",
            name="ck_review_items_score_snapshot_range",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND resolved_at IS NULL) OR "
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL)",
            name="ck_review_items_lifecycle",
        ),
        Index(
            "ix_review_items_field_confidence_assessment_id",
            "field_confidence_assessment_id",
        ),
        Index("ix_review_items_candidate_field_id", "candidate_field_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    review_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_cases.id", ondelete="RESTRICT"), nullable=False
    )
    item_key: Mapped[str] = mapped_column(String(80), nullable=False)
    scope: Mapped[ReviewItemScope] = mapped_column(
        constrained_enum(ReviewItemScope, "ck_review_items_scope"), nullable=False
    )
    field_confidence_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("field_confidence_assessments.id", ondelete="RESTRICT")
    )
    candidate_field_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_fields.id", ondelete="RESTRICT")
    )
    status: Mapped[ReviewItemStatus] = mapped_column(
        constrained_enum(ReviewItemStatus, "ck_review_items_status"), nullable=False
    )
    priority: Mapped[ReviewPriority] = mapped_column(
        constrained_enum(ReviewPriority, "ck_review_items_priority"), nullable=False
    )
    policy_version: Mapped[ConfidencePolicyVersion] = mapped_column(
        constrained_enum(ConfidencePolicyVersion, "ck_review_items_policy_version"),
        nullable=False,
    )
    field_path_snapshot: Mapped[str | None] = mapped_column(String(255))
    candidate_value_type_snapshot: Mapped[CandidateValueType | None] = mapped_column(
        constrained_enum(CandidateValueType, "ck_review_items_candidate_value_type")
    )
    candidate_value_snapshot: Mapped[Any] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        nullable=True,
    )
    confidence_score_snapshot: Mapped[int | None] = mapped_column(Integer)
    review_reason_codes_snapshot: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    component_breakdown_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    review_case: Mapped[ReviewCase] = relationship(back_populates="items")
    field_confidence_assessment: Mapped[FieldConfidenceAssessment | None] = relationship()
    candidate_field: Mapped[CandidateField | None] = relationship()
    decision: Mapped["ReviewDecision | None"] = relationship(
        back_populates="review_item", uselist=False
    )

    @property
    def field_verification_id(self) -> uuid.UUID | None:
        if self.field_confidence_assessment is None:
            return None
        return self.field_confidence_assessment.field_verification_id


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        UniqueConstraint("review_item_id", name="uq_review_decisions_review_item"),
        CheckConstraint(
            "length(trim(reviewer_identifier)) > 0",
            name="ck_review_decisions_reviewer_nonblank",
        ),
        CheckConstraint(
            "(decision = 'CORRECT_AND_APPROVE' "
            "AND corrected_value_type IS NOT NULL) OR "
            "(decision <> 'CORRECT_AND_APPROVE' "
            "AND corrected_value_type IS NULL AND corrected_value IS NULL)",
            name="ck_review_decisions_corrected_value",
        ),
        CheckConstraint(
            "decision = 'APPROVE_AS_IS' OR "
            "(decision_note IS NOT NULL AND length(trim(decision_note)) > 0)",
            name="ck_review_decisions_required_note",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    review_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_items.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[ReviewDecisionType] = mapped_column(
        constrained_enum(ReviewDecisionType, "ck_review_decisions_decision"),
        nullable=False,
    )
    reviewer_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text)
    original_value_snapshot: Mapped[Any] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        nullable=True,
    )
    original_value_type_snapshot: Mapped[CandidateValueType | None] = mapped_column(
        constrained_enum(CandidateValueType, "ck_review_decisions_original_value_type")
    )
    corrected_value_type: Mapped[CandidateValueType | None] = mapped_column(
        constrained_enum(CandidateValueType, "ck_review_decisions_corrected_value_type")
    )
    corrected_value: Mapped[Any] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        nullable=True,
    )
    evidence_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    review_item: Mapped[ReviewItem] = relationship(back_populates="decision")
