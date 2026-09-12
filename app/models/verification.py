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
from app.models.evidence import Evidence
from app.models.source_registry import SourceClass, constrained_enum


class VerificationRunStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class VerificationTriggerType(enum.StrEnum):
    MANUAL = "MANUAL"
    AUTOMATED = "AUTOMATED"
    RETRY = "RETRY"


class FieldVerificationStatus(enum.StrEnum):
    PENDING = "PENDING"
    FINALIZED = "FINALIZED"


class FieldVerificationOutcome(enum.StrEnum):
    CONFIRMED = "CONFIRMED"
    CONFLICT = "CONFLICT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class VerificationReasonCode(enum.StrEnum):
    AUTHORITATIVE_SUPPORT = "AUTHORITATIVE_SUPPORT"
    MULTI_SOURCE_SUPPORT = "MULTI_SOURCE_SUPPORT"
    AUTHORITATIVE_CONFLICT = "AUTHORITATIVE_CONFLICT"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    NO_EVIDENCE = "NO_EVIDENCE"
    ONLY_SECONDARY_EVIDENCE = "ONLY_SECONDARY_EVIDENCE"
    INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"
    MANUALLY_MARKED_NOT_APPLICABLE = "MANUALLY_MARKED_NOT_APPLICABLE"


class EvidenceAssessmentType(enum.StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CONTEXT_ONLY = "CONTEXT_ONLY"


class VerificationRun(Base):
    __tablename__ = "verification_runs"
    __table_args__ = (
        CheckConstraint(
            "fields_total >= 0 AND fields_confirmed >= 0 "
            "AND fields_conflicted >= 0 AND fields_insufficient >= 0 "
            "AND fields_not_applicable >= 0",
            name="ck_verification_runs_nonnegative_counters",
        ),
        CheckConstraint(
            "fields_confirmed + fields_conflicted + fields_insufficient "
            "+ fields_not_applicable <= fields_total",
            name="ck_verification_runs_counter_total",
        ),
        CheckConstraint(
            "length(candidate_revision_hash_snapshot) = 64 "
            "AND candidate_revision_hash_snapshot = "
            "lower(candidate_revision_hash_snapshot)",
            name="ck_verification_runs_revision_hash_format",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND started_at IS NULL AND completed_at IS NULL) "
            "OR (status = 'RUNNING' AND started_at IS NOT NULL "
            "AND completed_at IS NULL) "
            "OR (status IN ('COMPLETED', 'PARTIAL', 'FAILED') "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_verification_runs_lifecycle_times",
        ),
        Index("ix_verification_runs_candidate_revision_id", "candidate_revision_id"),
        Index("ix_verification_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_candidate_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    candidate_revision_hash_snapshot: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    status: Mapped[VerificationRunStatus] = mapped_column(
        constrained_enum(VerificationRunStatus, "ck_verification_runs_status"),
        nullable=False,
        default=VerificationRunStatus.PENDING,
    )
    trigger_type: Mapped[VerificationTriggerType] = mapped_column(
        constrained_enum(
            VerificationTriggerType, "ck_verification_runs_trigger_type"
        ),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fields_total: Mapped[int] = mapped_column(Integer, nullable=False)
    fields_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_conflicted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_insufficient: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_not_applicable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    field_verifications: Mapped[list["FieldVerification"]] = relationship(
        back_populates="verification_run",
        order_by="FieldVerification.created_at",
    )


class FieldVerification(Base):
    __tablename__ = "field_verifications"
    __table_args__ = (
        UniqueConstraint(
            "verification_run_id",
            "candidate_field_id",
            name="uq_field_verifications_run_field",
        ),
        CheckConstraint(
            "authoritative_support_count >= 0 AND official_support_count >= 0 "
            "AND secondary_support_count >= 0 "
            "AND authoritative_conflict_count >= 0 "
            "AND official_conflict_count >= 0 "
            "AND secondary_conflict_count >= 0 AND evidence_count >= 0",
            name="ck_field_verifications_nonnegative_counts",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND outcome IS NULL AND reason_code IS NULL "
            "AND finding_summary IS NULL AND finalized_at IS NULL) "
            "OR (status = 'FINALIZED' AND outcome IS NOT NULL "
            "AND reason_code IS NOT NULL AND finding_summary IS NOT NULL "
            "AND finalized_at IS NOT NULL)",
            name="ck_field_verifications_finalization",
        ),
        Index("ix_field_verifications_candidate_field_id", "candidate_field_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    verification_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_fields.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_field_path_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_field_value_snapshot: Mapped[Any] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    candidate_field_type_snapshot: Mapped[CandidateValueType] = mapped_column(
        constrained_enum(
            CandidateValueType, "ck_field_verifications_candidate_value_type"
        ),
        nullable=False,
    )
    status: Mapped[FieldVerificationStatus] = mapped_column(
        constrained_enum(
            FieldVerificationStatus, "ck_field_verifications_status"
        ),
        nullable=False,
        default=FieldVerificationStatus.PENDING,
    )
    outcome: Mapped[FieldVerificationOutcome | None] = mapped_column(
        constrained_enum(FieldVerificationOutcome, "ck_field_verifications_outcome")
    )
    reason_code: Mapped[VerificationReasonCode | None] = mapped_column(
        constrained_enum(VerificationReasonCode, "ck_field_verifications_reason")
    )
    finding_summary: Mapped[str | None] = mapped_column(Text)
    authoritative_support_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    official_support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    secondary_support_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    authoritative_conflict_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    official_conflict_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    secondary_conflict_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    verification_run: Mapped[VerificationRun] = relationship(
        back_populates="field_verifications"
    )
    candidate_field: Mapped[CandidateField] = relationship()
    assessments: Mapped[list["VerificationEvidenceAssessment"]] = relationship(
        back_populates="field_verification",
        order_by="VerificationEvidenceAssessment.created_at",
    )


class VerificationEvidenceAssessment(Base):
    __tablename__ = "verification_evidence_assessments"
    __table_args__ = (
        UniqueConstraint(
            "field_verification_id",
            "evidence_id",
            name="uq_verification_assessments_field_evidence",
        ),
        Index("ix_verification_assessments_evidence_id", "evidence_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    field_verification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("field_verifications.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"), nullable=False
    )
    assessment: Mapped[EvidenceAssessmentType] = mapped_column(
        constrained_enum(
            EvidenceAssessmentType, "ck_verification_assessments_assessment"
        ),
        nullable=False,
    )
    asserted_value: Mapped[Any] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    asserted_value_type: Mapped[CandidateValueType | None] = mapped_column(
        constrained_enum(
            CandidateValueType, "ck_verification_assessments_asserted_value_type"
        )
    )
    source_class_snapshot: Mapped[SourceClass] = mapped_column(
        constrained_enum(SourceClass, "ck_verification_assessments_source_class"),
        nullable=False,
    )
    assessment_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    field_verification: Mapped[FieldVerification] = relationship(
        back_populates="assessments"
    )
    evidence: Mapped[Evidence] = relationship()

    @property
    def source_document_id(self) -> uuid.UUID:
        return self.evidence.source_document_id

    @property
    def source_endpoint_id(self) -> uuid.UUID:
        return self.evidence.source_document.source_endpoint_id

    @property
    def source_class(self) -> SourceClass:
        return self.source_class_snapshot

    @property
    def evidence_excerpt(self) -> str:
        return self.evidence.excerpt

    @property
    def evidence_source_locator(self) -> str | None:
        return self.evidence.source_locator
