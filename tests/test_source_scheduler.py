import logging
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from app.core.config import Settings
from app.models.pipeline import PipelineTriggerType
from app.models.source_registry import SourceEndpoint, SourceScheduleGroup
from app.services.pipeline_orchestrator import PipelineStatus, PipelineSummary
from app.services.source_scheduler import (
    SchedulerSelection,
    SchedulerSummary,
    SourceSchedulerService,
    source_schedule_catalog,
)
from tests.factories import create_authority, create_endpoint
from workers import scheduler as scheduler_command

NOW = datetime(2026, 9, 14, 2, 30, tzinfo=UTC)


def _service(db_session) -> SourceSchedulerService:
    return SourceSchedulerService(db_session, Settings(), logging.getLogger(__name__))


def test_catalog_covers_pipeline_sources_with_bounded_schedules() -> None:
    catalog = source_schedule_catalog()

    assert tuple(sorted(catalog)) == (
        "APSC",
        "ASDMA_ASSAM",
        "DEE_ASSAM",
        "DME_ASSAM",
        "SLPRB_ASSAM",
    )
    assert catalog["APSC"].group == SourceScheduleGroup.HIGH_PRIORITY
    assert all(item.poll_interval_minutes >= 15 for item in catalog.values())
    assert all(1 <= item.requests_per_minute <= 60 for item in catalog.values())


def test_selection_is_priority_then_code_and_supports_groups(db_session) -> None:
    service = _service(db_session)

    assert service.select_sources(SchedulerSelection.ALL, evaluated_at=NOW) == (
        "APSC",
        "SLPRB_ASSAM",
        "DEE_ASSAM",
        "DME_ASSAM",
        "ASDMA_ASSAM",
    )
    assert service.select_sources(
        SchedulerSelection.GROUP,
        group=SourceScheduleGroup.HIGH_PRIORITY,
        evaluated_at=NOW,
    ) == ("APSC", "SLPRB_ASSAM", "DEE_ASSAM")


def test_due_selection_uses_registry_attempt_time_and_disabled_state(client, db_session) -> None:
    authority = create_authority(client)
    recent = create_endpoint(
        client,
        authority["id"],
        schedule_group="HIGH_PRIORITY",
        poll_interval_minutes=360,
        priority=10,
    )
    endpoint = db_session.get(SourceEndpoint, UUID(recent["id"]))
    assert endpoint is not None
    endpoint.last_attempted_at = NOW - timedelta(minutes=30)
    db_session.commit()

    selected = _service(db_session).select_sources(SchedulerSelection.DUE, evaluated_at=NOW)

    assert "APSC" not in selected
    assert "SLPRB_ASSAM" in selected

    endpoint.discovery_enabled = False
    db_session.commit()
    try:
        _service(db_session).select_sources(
            SchedulerSelection.SOURCE, source="APSC", evaluated_at=NOW
        )
    except ValueError as error:
        assert "disabled source" in str(error)
    else:
        raise AssertionError("disabled source should not be selected")


def test_scheduler_isolates_one_source_failure(monkeypatch, db_session) -> None:
    calls: list[str] = []

    def execute(_self, _orchestrator, *, source, **_kwargs):
        calls.append(source)
        if source == "APSC":
            raise OSError("controlled outage")
        summary = PipelineSummary(
            source=source,
            authority_code=source,
            dry_run=True,
            status=PipelineStatus.SUCCESS,
        )
        return summary, SimpleNamespace(id=f"run-{source}")

    monkeypatch.setattr("app.services.source_scheduler.PipelineHistoryService.execute", execute)
    summary = _service(db_session).run(
        SchedulerSelection.ALL,
        dry_run=True,
        trigger_type=PipelineTriggerType.SCHEDULED,
        evaluated_at=NOW,
    )

    assert calls == list(summary.selected_sources)
    assert summary.results[0].status == PipelineStatus.FAILED
    assert all(item.status == PipelineStatus.SUCCESS for item in summary.results[1:])
    assert summary.failed == 1


def test_scheduler_cli_maps_due_and_dry_run(monkeypatch, db_session, capsys) -> None:
    captured = {}

    class StubScheduler:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self, selection, **kwargs):
            captured.update(selection=selection, **kwargs)
            return SchedulerSummary(selection, kwargs["dry_run"], ("APSC",))

    monkeypatch.setattr(scheduler_command, "SourceSchedulerService", StubScheduler)
    monkeypatch.setattr(scheduler_command, "SessionLocal", lambda: nullcontext(db_session))

    result = scheduler_command.main(
        ["--due", "--dry-run", "--trigger", PipelineTriggerType.SCHEDULED]
    )

    assert result == 0
    assert captured["selection"] == SchedulerSelection.DUE
    assert captured["dry_run"] is True
    assert captured["trigger_type"] == PipelineTriggerType.SCHEDULED
    assert "Selected: APSC" in capsys.readouterr().out
