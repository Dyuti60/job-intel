import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.monitoring import (
    OperationalHealthStatus,
    OperationalNotificationChannel,
    OperationalNotificationDeliveryStatus,
    OperationalNotificationSeverity,
    OperationalNotificationType,
)
from app.models.pipeline import PipelineRunStatus, PipelineStage, PipelineTriggerType


class MonitoringSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class StageDurationTrendRead(MonitoringSchema):
    stage: str
    samples: int
    latest_duration_ms: int
    average_duration_ms: int
    minimum_duration_ms: int
    maximum_duration_ms: int


class OperationalAlertRead(MonitoringSchema):
    event_type: OperationalNotificationType
    severity: OperationalNotificationSeverity
    pipeline_run_id: uuid.UUID | None
    message: str


class OperationalPipelineRunReference(MonitoringSchema):
    id: uuid.UUID
    source_code: str
    trigger_type: PipelineTriggerType
    status: PipelineRunStatus
    dry_run: bool
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    error_stage: PipelineStage | None
    error_code: str | None


class SourceOperationalHealthRead(MonitoringSchema):
    source_code: str
    status: OperationalHealthStatus
    evaluated_at: datetime
    current_runs: list[OperationalPipelineRunReference]
    stale_running_runs: list[OperationalPipelineRunReference]
    last_run: OperationalPipelineRunReference | None
    last_successful_run: OperationalPipelineRunReference | None
    last_failed_run: OperationalPipelineRunReference | None
    last_failure_summary: str | None
    seconds_since_last_success: int | None
    queued_review_cases: int
    in_review_cases: int
    stage_trends: list[StageDurationTrendRead]
    alerts: list[OperationalAlertRead]
    pipeline_runs_url: str
    review_queue_url: str


class OperationalNotificationRead(MonitoringSchema):
    id: uuid.UUID
    source_code: str
    pipeline_run_id: uuid.UUID | None
    event_type: OperationalNotificationType
    severity: OperationalNotificationSeverity
    channel: OperationalNotificationChannel
    deduplication_key: str
    message: str
    delivery_status: OperationalNotificationDeliveryStatus
    delivery_error: str | None
    created_at: datetime
    delivered_at: datetime | None
