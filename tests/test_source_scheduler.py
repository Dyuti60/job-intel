import logging
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import Settings
from app.models.pipeline import PipelineRun, PipelineTriggerType
from app.models.source_registry import SourceEndpoint, SourceScheduleGroup
from app.services.pipeline_orchestrator import PipelineStatus, PipelineSummary
from app.services.source_scheduler import (
    SchedulerSelection,
    SchedulerSummary,
    SourceSchedulerService,
    format_scheduler_summary,
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
        "DHS_ASSAM",
        "DME_ASSAM",
        "DTE_ASSAM",
        "FREMAA_ASSAM",
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
        "DHS_ASSAM",
        "DME_ASSAM",
        "DTE_ASSAM",
        "ASDMA_ASSAM",
        "FREMAA_ASSAM",
    )
    assert service.select_sources(
        SchedulerSelection.GROUP,
        group=SourceScheduleGroup.HIGH_PRIORITY,
        evaluated_at=NOW,
    ) == (
        "APSC",
        "SLPRB_ASSAM",
        "DEE_ASSAM",
        "DHS_ASSAM",
        "DTE_ASSAM",
    )


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
        execute_no_commit=True,
        trigger_type=PipelineTriggerType.SCHEDULED,
        evaluated_at=NOW,
    )

    assert calls == list(summary.selected_sources)
    assert summary.results[0].status == PipelineStatus.FAILED
    assert all(item.status == PipelineStatus.SUCCESS for item in summary.results[1:])
    assert summary.failed == 1


def test_fast_dry_run_previews_all_selection_modes_without_pipeline_side_effects(
    monkeypatch, client, db_session
) -> None:
    authority = create_authority(client)
    endpoint_data = create_endpoint(
        client,
        authority["id"],
        schedule_group="HIGH_PRIORITY",
        poll_interval_minutes=360,
        priority=10,
    )
    endpoint = db_session.get(SourceEndpoint, UUID(endpoint_data["id"]))
    assert endpoint is not None
    endpoint.last_attempted_at = NOW - timedelta(minutes=30)
    endpoint.last_successful_at = NOW - timedelta(days=1)
    db_session.commit()
    before = (endpoint.last_attempted_at, endpoint.last_successful_at)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("dry-run preview must not construct or execute a pipeline")

    monkeypatch.setattr(
        "app.services.source_scheduler.PipelineOrchestratorService", forbidden
    )
    monkeypatch.setattr("app.services.source_scheduler.PipelineAdvisoryLock", forbidden)
    service = _service(db_session)

    source = service.run(
        SchedulerSelection.SOURCE, source="APSC", dry_run=True, evaluated_at=NOW
    )
    group = service.run(
        SchedulerSelection.GROUP,
        group=SourceScheduleGroup.HIGH_PRIORITY,
        dry_run=True,
        evaluated_at=NOW,
    )
    due = service.run(SchedulerSelection.DUE, dry_run=True, evaluated_at=NOW)
    all_enabled = service.run(SchedulerSelection.ALL, dry_run=True, evaluated_at=NOW)

    assert source.selected_sources == ("APSC",)
    assert group.selected_sources == (
        "APSC",
        "SLPRB_ASSAM",
        "DEE_ASSAM",
        "DHS_ASSAM",
        "DTE_ASSAM",
    )
    assert "APSC" not in due.selected_sources
    assert all_enabled.selected_sources == (
        "APSC",
        "SLPRB_ASSAM",
        "DEE_ASSAM",
        "DHS_ASSAM",
        "DME_ASSAM",
        "DTE_ASSAM",
        "ASDMA_ASSAM",
        "FREMAA_ASSAM",
    )
    assert source.results == []
    assert source.previews[0].due is False
    assert source.previews[0].last_attempted_at == before[0]
    assert format_scheduler_summary(source) == format_scheduler_summary(source)
    assert db_session.scalar(select(func.count()).select_from(PipelineRun)) == 0
    db_session.refresh(endpoint)
    assert endpoint.last_attempted_at == before[0].replace(tzinfo=None)
    assert endpoint.last_successful_at == before[1].replace(tzinfo=None)


def test_execute_no_commit_and_normal_execution_pass_distinct_pipeline_modes(
    monkeypatch, client, db_session
) -> None:
    authority = create_authority(client)
    endpoint_data = create_endpoint(client, authority["id"])
    endpoint = db_session.get(SourceEndpoint, UUID(endpoint_data["id"]))
    assert endpoint is not None
    calls: list[bool] = []

    def execute(_self, _orchestrator, *, source, dry_run, **_kwargs):
        calls.append(dry_run)
        summary = PipelineSummary(
            source=source,
            authority_code=source,
            dry_run=dry_run,
            status=PipelineStatus.SUCCESS,
        )
        return summary, SimpleNamespace(id=f"run-{len(calls)}")

    monkeypatch.setattr("app.services.source_scheduler.PipelineHistoryService.execute", execute)
    service = _service(db_session)
    previewed_execution = service.run(
        SchedulerSelection.SOURCE,
        source="APSC",
        execute_no_commit=True,
        evaluated_at=NOW,
    )
    db_session.refresh(endpoint)
    assert endpoint.last_attempted_at is None and endpoint.last_successful_at is None

    normal = service.run(
        SchedulerSelection.SOURCE,
        source="APSC",
        evaluated_at=NOW,
    )
    db_session.refresh(endpoint)

    assert calls == [True, False]
    assert previewed_execution.execute_no_commit is True
    assert normal.execute_no_commit is False
    assert endpoint.last_attempted_at == endpoint.last_successful_at == NOW.replace(tzinfo=None)


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
    assert captured["execute_no_commit"] is False
    assert captured["trigger_type"] == PipelineTriggerType.SCHEDULED
    assert "Selected: APSC" in capsys.readouterr().out


def test_scheduler_cli_execute_no_commit_and_mode_help(monkeypatch, db_session, capsys) -> None:
    captured = {}

    class StubScheduler:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self, selection, **kwargs):
            captured.update(selection=selection, **kwargs)
            return SchedulerSummary(
                selection,
                kwargs["dry_run"],
                ("ASDMA_ASSAM",),
                execute_no_commit=kwargs["execute_no_commit"],
            )

    monkeypatch.setattr(scheduler_command, "SourceSchedulerService", StubScheduler)
    monkeypatch.setattr(scheduler_command, "SessionLocal", lambda: nullcontext(db_session))

    assert scheduler_command.main(["--source", "ASDMA_ASSAM", "--execute-no-commit"]) == 0
    assert captured["execute_no_commit"] is True and captured["dry_run"] is False
    help_text = scheduler_command.build_parser().format_help()
    assert "Preview scheduler selection only" in help_text
    assert "complete source pipeline" in help_text
    assert "Mode: EXECUTE_NO_COMMIT" in capsys.readouterr().out
