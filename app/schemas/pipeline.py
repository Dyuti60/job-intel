import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.pipeline import (
    PipelineRunStatus,
    PipelineStage,
    PipelineStageStatus,
    PipelineTriggerType,
)


class PipelineSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class PipelineStageRunRead(PipelineSchema):
    id: uuid.UUID
    pipeline_run_id: uuid.UUID
    stage: PipelineStage
    status: PipelineStageStatus
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    summary_json: dict[str, Any]
    error_code: str | None
    error_message: str | None
    created_at: datetime


class PipelineRunSummary(PipelineSchema):
    id: uuid.UUID
    source_code: str
    authority_code: str
    trigger_type: PipelineTriggerType
    status: PipelineRunStatus
    dry_run: bool
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    discovery_status: PipelineStageStatus | None
    verification_status: PipelineStageStatus | None
    publisher_status: PipelineStageStatus | None
    review_cases_queued: int
    masters_created: int
    masters_updated: int
    masters_unchanged: int
    error_stage: PipelineStage | None
    error_code: str | None
    error_message: str | None
    created_at: datetime


class PipelineRunDetail(PipelineRunSummary):
    summary_json: dict[str, Any]
    stages: list[PipelineStageRunRead]
