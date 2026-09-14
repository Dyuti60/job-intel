import enum
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.pipeline import PipelineTriggerType
from app.models.source_registry import (
    RecruitingAuthority,
    SourceEndpoint,
    SourceScheduleGroup,
    SourceStatus,
)
from app.services.pipeline_history import PipelineHistoryService
from app.services.pipeline_lock import PipelineAdvisoryLock
from app.services.pipeline_orchestrator import (
    PIPELINE_SOURCES,
    PipelineOrchestratorService,
    PipelineStatus,
    PipelineSummary,
)
from sources.adapters.official_recruitment_archive import OFFICIAL_ARCHIVE_SOURCES


class SchedulerSelection(enum.StrEnum):
    SOURCE = "SOURCE"
    GROUP = "GROUP"
    DUE = "DUE"
    ALL = "ALL"


@dataclass(frozen=True)
class SourceSchedule:
    source_code: str
    group: SourceScheduleGroup
    poll_interval_minutes: int
    priority: int
    requests_per_minute: int


@dataclass
class ScheduledSourceResult:
    source_code: str
    status: str
    pipeline_run_id: str | None = None
    summary: PipelineSummary | None = None
    error: str | None = None


@dataclass
class SchedulerSummary:
    selection: SchedulerSelection
    dry_run: bool
    selected_sources: tuple[str, ...]
    results: list[ScheduledSourceResult] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return sum(item.status == PipelineStatus.FAILED for item in self.results)


def source_schedule_catalog() -> dict[str, SourceSchedule]:
    schedules = {"APSC": SourceSchedule("APSC", SourceScheduleGroup.HIGH_PRIORITY, 360, 10, 6)}
    schedules.update(
        {
            code: SourceSchedule(
                code,
                config.schedule_group,
                config.poll_interval_minutes,
                config.priority,
                config.requests_per_minute,
            )
            for code, config in OFFICIAL_ARCHIVE_SOURCES.items()
        }
    )
    if set(schedules) != set(PIPELINE_SOURCES):
        raise RuntimeError("Every pipeline source must have deterministic schedule metadata")
    return schedules


class SourceSchedulerService:
    """Select and execute registered source pipelines with per-source isolation."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        logger: logging.Logger | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)

    def select_sources(
        self,
        selection: SchedulerSelection,
        *,
        source: str | None = None,
        group: SourceScheduleGroup | None = None,
        evaluated_at: datetime | None = None,
    ) -> tuple[str, ...]:
        now = evaluated_at or datetime.now(UTC)
        catalog = source_schedule_catalog()
        endpoints = {
            authority.code: endpoint
            for authority, endpoint in self.session.execute(
                select(RecruitingAuthority, SourceEndpoint).join(
                    SourceEndpoint,
                    SourceEndpoint.recruiting_authority_id == RecruitingAuthority.id,
                )
            )
        }
        candidates: list[tuple[int, str]] = []
        for code, default in catalog.items():
            endpoint = endpoints.get(code)
            if endpoint is not None and (
                endpoint.status != SourceStatus.ACTIVE or not endpoint.discovery_enabled
            ):
                continue
            schedule_group = endpoint.schedule_group if endpoint else default.group
            priority = endpoint.priority if endpoint else default.priority
            interval = endpoint.poll_interval_minutes if endpoint else default.poll_interval_minutes
            if selection == SchedulerSelection.SOURCE and code != (source or "").upper():
                continue
            if selection == SchedulerSelection.GROUP and schedule_group != group:
                continue
            if (
                selection == SchedulerSelection.DUE
                and endpoint
                and endpoint.last_attempted_at
                and endpoint.last_attempted_at + timedelta(minutes=interval) > now
            ):
                continue
            candidates.append((priority, code))
        if selection == SchedulerSelection.SOURCE and not candidates:
            raise ValueError(f"Unknown or disabled source: {(source or '').upper()}")
        if selection == SchedulerSelection.GROUP and group is None:
            raise ValueError("A schedule group is required")
        return tuple(code for _, code in sorted(candidates))

    def run(
        self,
        selection: SchedulerSelection,
        *,
        source: str | None = None,
        group: SourceScheduleGroup | None = None,
        dry_run: bool = False,
        trigger_type: PipelineTriggerType = PipelineTriggerType.CLI,
        evaluated_at: datetime | None = None,
    ) -> SchedulerSummary:
        started_at = evaluated_at or datetime.now(UTC)
        selected = self.select_sources(
            selection, source=source, group=group, evaluated_at=started_at
        )
        aggregate = SchedulerSummary(selection, dry_run, selected)
        engine = self.session.get_bind()
        for code in selected:
            try:
                with PipelineAdvisoryLock(engine, code).acquire() as acquired:
                    if not acquired:
                        aggregate.results.append(ScheduledSourceResult(code, "SKIPPED_LOCKED"))
                        continue
                    summary, pipeline_run = PipelineHistoryService(self.session).execute(
                        PipelineOrchestratorService(self.session, self.settings, self.logger),
                        source=code,
                        dry_run=dry_run,
                        trigger_type=trigger_type,
                    )
                    if not dry_run:
                        self._record_attempt(code, started_at, summary.status)
                    aggregate.results.append(
                        ScheduledSourceResult(
                            code,
                            summary.status.value,
                            str(pipeline_run.id),
                            summary,
                        )
                    )
            except Exception as error:
                self.session.rollback()
                self.logger.exception("scheduled_source_failed source=%s", code)
                aggregate.results.append(
                    ScheduledSourceResult(
                        code,
                        PipelineStatus.FAILED.value,
                        error=f"{type(error).__name__}: {error}"[:2000],
                    )
                )
        return aggregate

    def _record_attempt(
        self, source_code: str, attempted_at: datetime, status: PipelineStatus
    ) -> None:
        endpoint = self.session.scalar(
            select(SourceEndpoint)
            .join(RecruitingAuthority)
            .where(RecruitingAuthority.code == source_code)
        )
        if endpoint is None:
            return
        endpoint.last_attempted_at = attempted_at
        if status == PipelineStatus.SUCCESS:
            endpoint.last_successful_at = attempted_at
        self.session.commit()


def format_scheduler_summary(summary: SchedulerSummary) -> str:
    lines = [
        "================================================",
        " Assam Job Intelligence - Multi-source scheduler",
        f" Selection: {summary.selection.value}",
        f" Dry run: {summary.dry_run}",
        f" Selected: {', '.join(summary.selected_sources) or 'none'}",
        "================================================",
    ]
    for result in summary.results:
        run = f" run={result.pipeline_run_id}" if result.pipeline_run_id else ""
        error = f" error={result.error}" if result.error else ""
        lines.append(f"{result.source_code}: {result.status}{run}{error}")
    lines.append(f"Failures: {summary.failed}")
    return "\n".join(lines)
