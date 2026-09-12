import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.candidates import RecruitmentCandidate, RecruitmentCandidateRevision
from app.models.monitoring import (
    OperationalHealthStatus,
    OperationalNotificationChannel,
    OperationalNotificationDeliveryStatus,
    OperationalNotificationEvent,
    OperationalNotificationSeverity,
    OperationalNotificationType,
)
from app.models.pipeline import PipelineRun, PipelineRunStatus, PipelineStage
from app.models.review import ReviewCase, ReviewCaseStatus
from app.models.source_registry import RecruitingAuthority
from app.repositories.monitoring import (
    OperationalMonitoringRepository,
    OperationalNotificationRepository,
)

MAX_OPERATIONAL_ERROR_LENGTH = 2000
_SOURCE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_CREDENTIAL_URL = re.compile(r"(\w+://)[^\s:/]+:[^\s@]+@")


@dataclass(frozen=True)
class StageDurationTrend:
    stage: str
    samples: int
    latest_duration_ms: int
    average_duration_ms: int
    minimum_duration_ms: int
    maximum_duration_ms: int


@dataclass(frozen=True)
class OperationalAlert:
    event_type: OperationalNotificationType
    severity: OperationalNotificationSeverity
    pipeline_run_id: uuid.UUID | None
    message: str


@dataclass(frozen=True)
class SourceOperationalHealth:
    source_code: str
    status: OperationalHealthStatus
    evaluated_at: datetime
    current_runs: tuple[PipelineRun, ...]
    stale_running_runs: tuple[PipelineRun, ...]
    last_run: PipelineRun | None
    last_successful_run: PipelineRun | None
    last_failed_run: PipelineRun | None
    last_failure_summary: str | None
    seconds_since_last_success: int | None
    queued_review_cases: int
    in_review_cases: int
    stage_trends: tuple[StageDurationTrend, ...]
    alerts: tuple[OperationalAlert, ...]
    pipeline_runs_url: str
    review_queue_url: str


@dataclass(frozen=True)
class MonitoringRunSummary:
    source_code: str
    status: str
    dry_run: bool
    alerts_detected: int
    notifications_created: int
    notifications_deduplicated: int
    deliveries_failed: int
    notification_ids: tuple[uuid.UUID, ...] = field(default_factory=tuple)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _bounded_error(value: str) -> str:
    first_line = value.strip().splitlines()[0] if value.strip() else ""
    return _CREDENTIAL_URL.sub(r"\1***:***@", first_line)[:MAX_OPERATIONAL_ERROR_LENGTH]


def normalize_source_code(source_code: str) -> str:
    normalized = source_code.strip().upper()
    if not _SOURCE_CODE.fullmatch(normalized):
        raise ValueError("Source code must be a stable uppercase identifier")
    return normalized


class OperationalMonitoringService:
    """Derive source health without mutating pipeline or recruitment history."""

    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = OperationalMonitoringRepository(session)

    def source_codes(self) -> list[str]:
        return self.repository.source_codes()

    def evaluate(
        self,
        source_code: str,
        *,
        evaluated_at: datetime | None = None,
    ) -> SourceOperationalHealth:
        source = normalize_source_code(source_code)
        now = _aware(evaluated_at or datetime.now(UTC))
        runs = self.repository.runs_for_source(source)
        current = tuple(self.repository.current_runs_for_source(source))
        stale_cutoff = now - timedelta(minutes=self.settings.monitor_running_stale_minutes)
        stale_running = tuple(
            run for run in current if _aware(run.started_at) <= stale_cutoff
        )
        completed = [run for run in runs if run.status != PipelineRunStatus.RUNNING]
        last_run = max(
            [*current, *completed],
            key=lambda run: (_aware(run.started_at), str(run.id)),
            default=None,
        )
        last_success = next(
            (run for run in completed if run.status == PipelineRunStatus.SUCCESS), None
        )
        last_failure = next(
            (run for run in completed if run.status == PipelineRunStatus.FAILED), None
        )
        last_completed = completed[0] if completed else None
        success_age = (
            max(
                0,
                int(
                    (
                        now
                        - _aware(last_success.completed_at or last_success.started_at)
                    ).total_seconds()
                ),
            )
            if last_success is not None
            else None
        )
        overdue = (
            success_age is not None
            and success_age > self.settings.monitor_success_stale_hours * 3600
        )

        if stale_running:
            status = OperationalHealthStatus.STALE
        elif current:
            status = OperationalHealthStatus.RUNNING
        elif last_completed is None:
            status = OperationalHealthStatus.NO_DATA
        elif last_completed.status == PipelineRunStatus.FAILED:
            status = OperationalHealthStatus.FAILED
        elif overdue:
            status = OperationalHealthStatus.STALE
        elif last_completed.status == PipelineRunStatus.PARTIAL:
            status = OperationalHealthStatus.DEGRADED
        else:
            status = OperationalHealthStatus.HEALTHY

        alerts: list[OperationalAlert] = []
        for run in stale_running:
            alerts.append(
                OperationalAlert(
                    event_type=OperationalNotificationType.RUNNING_STALE,
                    severity=OperationalNotificationSeverity.CRITICAL,
                    pipeline_run_id=run.id,
                    message=(
                        f"{source} pipeline run {run.id} has remained RUNNING beyond "
                        f"{self.settings.monitor_running_stale_minutes} minutes."
                    ),
                )
            )
        if (
            last_failure is not None
            and (
                last_success is None
                or _aware(last_failure.started_at) > _aware(last_success.started_at)
            )
        ):
            detail = f" at {last_failure.error_stage.value}" if last_failure.error_stage else ""
            code = f" ({last_failure.error_code})" if last_failure.error_code else ""
            alerts.append(
                OperationalAlert(
                    event_type=OperationalNotificationType.PIPELINE_FAILED,
                    severity=OperationalNotificationSeverity.CRITICAL,
                    pipeline_run_id=last_failure.id,
                    message=f"{source} pipeline run {last_failure.id} failed{detail}{code}.",
                )
            )
        if overdue and not current and last_success is not None:
            alerts.append(
                OperationalAlert(
                    event_type=OperationalNotificationType.SUCCESS_OVERDUE,
                    severity=OperationalNotificationSeverity.WARNING,
                    pipeline_run_id=last_success.id,
                    message=(
                        f"{source} has no successful pipeline completion within "
                        f"{self.settings.monitor_success_stale_hours} hours."
                    ),
                )
            )

        return SourceOperationalHealth(
            source_code=source,
            status=status,
            evaluated_at=now,
            current_runs=current,
            stale_running_runs=stale_running,
            last_run=last_run,
            last_successful_run=last_success,
            last_failed_run=last_failure,
            last_failure_summary=(
                _bounded_error(last_failure.error_message)
                if last_failure is not None and last_failure.error_message
                else None
            ),
            seconds_since_last_success=success_age,
            queued_review_cases=self._review_count(source, ReviewCaseStatus.QUEUED),
            in_review_cases=self._review_count(source, ReviewCaseStatus.IN_REVIEW),
            stage_trends=self._stage_trends(source),
            alerts=tuple(alerts),
            pipeline_runs_url=f"/api/v1/pipeline-runs?source={source}",
            review_queue_url="/review",
        )

    def _review_count(self, source_code: str, status: ReviewCaseStatus) -> int:
        return int(
            self.session.scalar(
                select(func.count(ReviewCase.id))
                .join(
                    RecruitmentCandidateRevision,
                    RecruitmentCandidateRevision.id == ReviewCase.candidate_revision_id,
                )
                .join(
                    RecruitmentCandidate,
                    RecruitmentCandidate.id
                    == RecruitmentCandidateRevision.recruitment_candidate_id,
                )
                .join(
                    RecruitingAuthority,
                    RecruitingAuthority.id == RecruitmentCandidate.recruiting_authority_id,
                )
                .where(RecruitingAuthority.code == source_code, ReviewCase.status == status)
            )
            or 0
        )

    def _stage_trends(self, source_code: str) -> tuple[StageDurationTrend, ...]:
        limit = self.settings.monitor_trend_run_limit
        result = []
        for stage in PipelineStage:
            durations = [
                record.duration_ms
                for record in self.repository.stage_runs_for_source(
                    source_code, stage=stage.value, limit=limit
                )
            ]
            if not durations:
                continue
            result.append(
                StageDurationTrend(
                    stage=stage.value,
                    samples=len(durations),
                    latest_duration_ms=durations[0],
                    average_duration_ms=round(sum(durations) / len(durations)),
                    minimum_duration_ms=min(durations),
                    maximum_duration_ms=max(durations),
                )
            )
        return tuple(result)


class LocalNotificationRouter:
    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger

    def channels(self) -> tuple[OperationalNotificationChannel, ...]:
        values = [
            item.strip().upper()
            for item in self.settings.monitor_notification_channels.split(",")
        ]
        if not values or any(not item for item in values):
            raise ValueError("AJI_MONITOR_NOTIFICATION_CHANNELS must not be empty")
        try:
            channels = tuple(dict.fromkeys(OperationalNotificationChannel(item) for item in values))
        except ValueError as error:
            raise ValueError("Notification channels must contain only LOG and FILE") from error
        if (
            OperationalNotificationChannel.FILE in channels
            and not self.settings.monitor_notification_file
        ):
            raise ValueError(
                "AJI_MONITOR_NOTIFICATION_FILE is required when FILE routing is enabled"
            )
        return channels

    def deliver(self, event: OperationalNotificationEvent) -> None:
        if event.channel == OperationalNotificationChannel.LOG:
            self.logger.warning(
                "operational_notification source=%s type=%s severity=%s run=%s message=%s",
                event.source_code,
                event.event_type.value,
                event.severity.value,
                event.pipeline_run_id,
                event.message,
            )
            return
        path = Path(self.settings.monitor_notification_file or "")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "id": str(event.id),
            "source_code": event.source_code,
            "pipeline_run_id": str(event.pipeline_run_id) if event.pipeline_run_id else None,
            "event_type": event.event_type.value,
            "severity": event.severity.value,
            "message": event.message,
            "created_at": _aware(event.created_at).isoformat(),
        }
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


class OperationalNotificationService:
    def __init__(self, session: Session, settings: Settings, logger: logging.Logger) -> None:
        self.session = session
        self.settings = settings
        self.health_service = OperationalMonitoringService(session, settings)
        self.repository = OperationalNotificationRepository(session)
        self.router = LocalNotificationRouter(settings, logger)

    def run(
        self,
        source_code: str,
        *,
        dry_run: bool = False,
        evaluated_at: datetime | None = None,
    ) -> MonitoringRunSummary:
        health = self.health_service.evaluate(source_code, evaluated_at=evaluated_at)
        channels = self.router.channels()
        created: list[uuid.UUID] = []
        deduplicated = 0
        failed = 0
        for alert in health.alerts:
            for channel in channels:
                key = self._deduplication_key(health.source_code, alert, channel)
                if self.repository.get_by_deduplication_key(key) is not None:
                    deduplicated += 1
                    continue
                if dry_run:
                    continue
                event = OperationalNotificationEvent(
                    source_code=health.source_code,
                    pipeline_run_id=alert.pipeline_run_id,
                    event_type=alert.event_type,
                    severity=alert.severity,
                    channel=channel,
                    deduplication_key=key,
                    message=alert.message[:MAX_OPERATIONAL_ERROR_LENGTH],
                    delivery_status=OperationalNotificationDeliveryStatus.PENDING,
                )
                if not self.repository.add_if_absent(event):
                    deduplicated += 1
                    continue
                try:
                    self.router.deliver(event)
                except (OSError, ValueError) as error:
                    event.delivery_status = OperationalNotificationDeliveryStatus.FAILED
                    event.delivery_error = _bounded_error(str(error))
                    failed += 1
                else:
                    event.delivery_status = OperationalNotificationDeliveryStatus.DELIVERED
                    event.delivered_at = _aware(evaluated_at or datetime.now(UTC))
                created.append(event.id)
        if not dry_run:
            self.session.commit()
        return MonitoringRunSummary(
            source_code=health.source_code,
            status=health.status,
            dry_run=dry_run,
            alerts_detected=len(health.alerts),
            notifications_created=len(created),
            notifications_deduplicated=deduplicated,
            deliveries_failed=failed,
            notification_ids=tuple(created),
        )

    @staticmethod
    def _deduplication_key(
        source_code: str,
        alert: OperationalAlert,
        channel: OperationalNotificationChannel,
    ) -> str:
        identity = {
            "channel": channel.value,
            "event_type": alert.event_type.value,
            "pipeline_run_id": str(alert.pipeline_run_id) if alert.pipeline_run_id else None,
            "source_code": source_code,
        }
        canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def list_events(
        self,
        *,
        source_code: str | None,
        event_type: OperationalNotificationType | None,
        channel: OperationalNotificationChannel | None,
        delivery_status: OperationalNotificationDeliveryStatus | None,
        offset: int,
        limit: int,
    ) -> list[OperationalNotificationEvent]:
        source = normalize_source_code(source_code) if source_code else None
        return self.repository.list(
            source_code=source,
            event_type=event_type,
            channel=channel,
            delivery_status=delivery_status,
            offset=offset,
            limit=limit,
        )
