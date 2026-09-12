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
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.source_registry import constrained_enum


class PipelineTriggerType(enum.StrEnum):
    MANUAL = "MANUAL"
    CLI = "CLI"
    GITHUB_ACTION = "GITHUB_ACTION"
    SCHEDULED = "SCHEDULED"


class PipelineRunStatus(enum.StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class PipelineStage(enum.StrEnum):
    DISCOVERY = "DISCOVERY"
    VERIFICATION = "VERIFICATION"
    MASTER_PUBLISHER = "MASTER_PUBLISHER"


class PipelineStageStatus(enum.StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_pipeline_runs_duration"
        ),
        CheckConstraint("review_cases_queued >= 0", name="ck_pipeline_runs_review_count"),
        CheckConstraint(
            "masters_created >= 0 AND masters_updated >= 0 AND masters_unchanged >= 0",
            name="ck_pipeline_runs_master_counts",
        ),
        CheckConstraint(
            "(status = 'RUNNING' AND completed_at IS NULL AND duration_ms IS NULL) OR "
            "(status IN ('SUCCESS', 'PARTIAL', 'FAILED') AND completed_at IS NOT NULL "
            "AND duration_ms IS NOT NULL)",
            name="ck_pipeline_runs_completion_shape",
        ),
        Index("ix_pipeline_runs_source_started", "source_code", "started_at"),
        Index("ix_pipeline_runs_status_started", "status", "started_at"),
        Index("ix_pipeline_runs_trigger_type", "trigger_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_code: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_type: Mapped[PipelineTriggerType] = mapped_column(
        constrained_enum(PipelineTriggerType, "ck_pipeline_runs_trigger_type"), nullable=False
    )
    status: Mapped[PipelineRunStatus] = mapped_column(
        constrained_enum(PipelineRunStatus, "ck_pipeline_runs_status"), nullable=False
    )
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    discovery_status: Mapped[PipelineStageStatus | None] = mapped_column(
        constrained_enum(PipelineStageStatus, "ck_pipeline_runs_discovery_status")
    )
    verification_status: Mapped[PipelineStageStatus | None] = mapped_column(
        constrained_enum(PipelineStageStatus, "ck_pipeline_runs_verification_status")
    )
    publisher_status: Mapped[PipelineStageStatus | None] = mapped_column(
        constrained_enum(PipelineStageStatus, "ck_pipeline_runs_publisher_status")
    )
    review_cases_queued: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    masters_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    masters_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    masters_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_stage: Mapped[PipelineStage | None] = mapped_column(
        constrained_enum(PipelineStage, "ck_pipeline_runs_error_stage")
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    stages: Mapped[list["PipelineStageRun"]] = relationship(
        back_populates="pipeline_run",
        order_by="PipelineStageRun.started_at",
    )


class PipelineStageRun(Base):
    __tablename__ = "pipeline_stage_runs"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "stage", name="uq_pipeline_stage_runs_run_stage"),
        CheckConstraint("duration_ms >= 0", name="ck_pipeline_stage_runs_duration"),
        Index("ix_pipeline_stage_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="RESTRICT"), nullable=False
    )
    stage: Mapped[PipelineStage] = mapped_column(
        constrained_enum(PipelineStage, "ck_pipeline_stage_runs_stage"), nullable=False
    )
    status: Mapped[PipelineStageStatus] = mapped_column(
        constrained_enum(PipelineStageStatus, "ck_pipeline_stage_runs_status"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    pipeline_run: Mapped[PipelineRun] = relationship(back_populates="stages")
