import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.source_registry import constrained_enum
from app.models.verification import FieldVerification, VerificationRun


class ConfidencePolicyVersion(enum.StrEnum):
    V1 = "V1"
    V2 = "V2"


class FieldCriticality(enum.StrEnum):
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"


class ReviewPriority(enum.StrEnum):
    NONE = "NONE"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReviewReasonCode(enum.StrEnum):
    FIELD_SCORE_BELOW_THRESHOLD = "FIELD_SCORE_BELOW_THRESHOLD"
    CRITICAL_FIELD_BELOW_THRESHOLD = "CRITICAL_FIELD_BELOW_THRESHOLD"
    AUTHORITATIVE_CONFLICT = "AUTHORITATIVE_CONFLICT"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    ONLY_SECONDARY_EVIDENCE = "ONLY_SECONDARY_EVIDENCE"
    CRITICAL_FIELD_NO_AUTHORITATIVE_SUPPORT = "CRITICAL_FIELD_NO_AUTHORITATIVE_SUPPORT"
    PARTIAL_VERIFICATION = "PARTIAL_VERIFICATION"
    REVISION_SCORE_BELOW_THRESHOLD = "REVISION_SCORE_BELOW_THRESHOLD"


class FieldConfidenceAssessment(Base):
    __tablename__ = "field_confidence_assessments"
    __table_args__ = (
        UniqueConstraint(
            "field_verification_id",
            "policy_version",
            name="uq_field_confidence_verification_policy",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_field_confidence_score_range",
        ),
        CheckConstraint(
            "length(input_hash) = 64 AND input_hash = lower(input_hash)",
            name="ck_field_confidence_input_hash_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    field_verification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("field_verifications.id", ondelete="RESTRICT"), nullable=False
    )
    policy_version: Mapped[ConfidencePolicyVersion] = mapped_column(
        constrained_enum(ConfidencePolicyVersion, "ck_field_confidence_policy_version"),
        nullable=False,
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    criticality: Mapped[FieldCriticality] = mapped_column(
        constrained_enum(FieldCriticality, "ck_field_confidence_criticality"),
        nullable=False,
    )
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    review_priority: Mapped[ReviewPriority] = mapped_column(
        constrained_enum(ReviewPriority, "ck_field_confidence_review_priority"),
        nullable=False,
    )
    review_reason_codes: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    component_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    field_verification: Mapped[FieldVerification] = relationship()


class RevisionConfidenceAssessment(Base):
    __tablename__ = "revision_confidence_assessments"
    __table_args__ = (
        UniqueConstraint(
            "verification_run_id",
            "policy_version",
            name="uq_revision_confidence_run_policy",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_revision_confidence_score_range",
        ),
        CheckConstraint(
            "coverage_ratio >= 0 AND coverage_ratio <= 1",
            name="ck_revision_confidence_coverage_range",
        ),
        CheckConstraint(
            "fields_total >= 0 AND fields_scored >= 0 "
            "AND fields_not_applicable >= 0 AND critical_fields_total >= 0 "
            "AND critical_fields_requiring_review >= 0 "
            "AND fields_requiring_review >= 0",
            name="ck_revision_confidence_nonnegative_counts",
        ),
        CheckConstraint(
            "fields_scored + fields_not_applicable <= fields_total "
            "AND fields_requiring_review <= fields_total "
            "AND critical_fields_requiring_review <= critical_fields_total "
            "AND critical_fields_total <= fields_total",
            name="ck_revision_confidence_count_relationships",
        ),
        CheckConstraint(
            "length(input_hash) = 64 AND input_hash = lower(input_hash)",
            name="ck_revision_confidence_input_hash_format",
        ),
        Index(
            "ix_revision_confidence_candidate_revision_id",
            "candidate_revision_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    verification_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_candidate_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    policy_version: Mapped[ConfidencePolicyVersion] = mapped_column(
        constrained_enum(ConfidencePolicyVersion, "ck_revision_confidence_policy_version"),
        nullable=False,
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    coverage_ratio: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    fields_total: Mapped[int] = mapped_column(Integer, nullable=False)
    fields_scored: Mapped[int] = mapped_column(Integer, nullable=False)
    fields_not_applicable: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_fields_total: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_fields_requiring_review: Mapped[int] = mapped_column(Integer, nullable=False)
    fields_requiring_review: Mapped[int] = mapped_column(Integer, nullable=False)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    review_priority: Mapped[ReviewPriority] = mapped_column(
        constrained_enum(ReviewPriority, "ck_revision_confidence_review_priority"),
        nullable=False,
    )
    review_reason_codes: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    component_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    verification_run: Mapped[VerificationRun] = relationship()
