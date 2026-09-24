import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.models.monitoring import (
    OperationalHealthStatus,
    OperationalNotificationChannel,
    OperationalNotificationDeliveryStatus,
    OperationalNotificationEvent,
    OperationalNotificationSeverity,
    OperationalNotificationType,
)
from app.models.pipeline import (
    PipelineRun,
    PipelineRunStatus,
    PipelineStage,
    PipelineStageRun,
    PipelineStageStatus,
    PipelineTriggerType,
)
from app.services.operational_monitoring import (
    OperationalMonitoringService,
    OperationalNotificationService,
)
from app.services.source_scheduler import SchedulerSelection, SchedulerSummary
from workers import monitoring as monitoring_command

NOW = datetime(2026, 9, 13, 6, 0, tzinfo=UTC)


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "database_url": "sqlite+pysqlite:///:memory:",
        "monitor_running_stale_minutes": 60,
        "monitor_success_stale_hours": 26,
        "monitor_trend_run_limit": 2,
        "monitor_notification_channels": "LOG",
        "monitor_notification_file": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _run(
    session,
    *,
    status: PipelineRunStatus,
    started_at: datetime,
    duration_ms: int = 100,
    error_message: str | None = None,
) -> PipelineRun:
    terminal = status != PipelineRunStatus.RUNNING
    run = PipelineRun(
        source_code="APSC",
        authority_code="APSC",
        trigger_type=PipelineTriggerType.SCHEDULED,
        status=status,
        dry_run=False,
        started_at=started_at,
        completed_at=started_at + timedelta(milliseconds=duration_ms) if terminal else None,
        duration_ms=duration_ms if terminal else None,
        discovery_status=(
            PipelineStageStatus.FAILED
            if status == PipelineRunStatus.FAILED
            else PipelineStageStatus.SUCCESS
            if terminal
            else None
        ),
        review_cases_queued=0,
        masters_created=0,
        masters_updated=0,
        masters_unchanged=0,
        error_stage=PipelineStage.DISCOVERY if status == PipelineRunStatus.FAILED else None,
        error_code="CONTROLLED_FAILURE" if status == PipelineRunStatus.FAILED else None,
        error_message=error_message,
        summary_json={},
    )
    session.add(run)
    session.flush()
    if terminal:
        session.add(
            PipelineStageRun(
                pipeline_run_id=run.id,
                stage=PipelineStage.DISCOVERY,
                status=run.discovery_status,
                started_at=started_at,
                completed_at=run.completed_at,
                duration_ms=duration_ms,
                summary_json={},
                error_code=run.error_code,
                error_message=error_message,
            )
        )
    session.commit()
    return run


def test_health_has_deterministic_empty_success_and_stage_trend_states(
    db_session, tmp_path
) -> None:
    service = OperationalMonitoringService(db_session, _settings(tmp_path))
    assert service.evaluate("apsc", evaluated_at=NOW).status == OperationalHealthStatus.NO_DATA

    older = _run(
        db_session,
        status=PipelineRunStatus.SUCCESS,
        started_at=NOW - timedelta(hours=2),
        duration_ms=100,
    )
    latest = _run(
        db_session,
        status=PipelineRunStatus.SUCCESS,
        started_at=NOW - timedelta(hours=1),
        duration_ms=300,
    )
    health = service.evaluate("APSC", evaluated_at=NOW)
    assert health.status == OperationalHealthStatus.HEALTHY
    assert health.last_run.id == latest.id
    assert health.last_successful_run.id == latest.id
    assert health.last_failed_run is None
    assert health.seconds_since_last_success == 3599
    assert health.pipeline_runs_url.endswith("source=APSC")
    assert health.review_queue_url == "/review"
    assert health.stage_trends[0].stage == "DISCOVERY"
    assert health.stage_trends[0].samples == 2
    assert health.stage_trends[0].latest_duration_ms == 300
    assert health.stage_trends[0].average_duration_ms == 200
    assert older.id != latest.id


@pytest.mark.parametrize(
    ("run_status", "age", "expected"),
    [
        (PipelineRunStatus.RUNNING, timedelta(minutes=10), OperationalHealthStatus.RUNNING),
        (PipelineRunStatus.RUNNING, timedelta(minutes=61), OperationalHealthStatus.STALE),
        (PipelineRunStatus.PARTIAL, timedelta(minutes=10), OperationalHealthStatus.DEGRADED),
        (PipelineRunStatus.FAILED, timedelta(minutes=10), OperationalHealthStatus.FAILED),
    ],
)
def test_health_status_precedence(db_session, tmp_path, run_status, age, expected) -> None:
    _run(db_session, status=run_status, started_at=NOW - age)
    health = OperationalMonitoringService(db_session, _settings(tmp_path)).evaluate(
        "APSC", evaluated_at=NOW
    )
    assert health.status == expected


def test_overdue_success_and_stale_running_create_explainable_alerts(db_session, tmp_path) -> None:
    success = _run(
        db_session,
        status=PipelineRunStatus.SUCCESS,
        started_at=NOW - timedelta(hours=28),
    )
    running = _run(
        db_session,
        status=PipelineRunStatus.RUNNING,
        started_at=NOW - timedelta(hours=2),
    )
    health = OperationalMonitoringService(db_session, _settings(tmp_path)).evaluate(
        "APSC", evaluated_at=NOW
    )
    assert health.status == OperationalHealthStatus.STALE
    assert health.stale_running_runs[0].id == running.id
    assert {alert.event_type for alert in health.alerts} == {
        OperationalNotificationType.RUNNING_STALE
    }

    running.status = PipelineRunStatus.FAILED
    running.completed_at = NOW - timedelta(hours=1)
    running.duration_ms = 3_600_000
    running.discovery_status = PipelineStageStatus.FAILED
    running.error_stage = PipelineStage.DISCOVERY
    running.error_code = "LATE_FAILURE"
    db_session.commit()
    health = OperationalMonitoringService(db_session, _settings(tmp_path)).evaluate(
        "APSC", evaluated_at=NOW
    )
    assert health.last_successful_run.id == success.id
    assert {alert.event_type for alert in health.alerts} == {
        OperationalNotificationType.PIPELINE_FAILED,
        OperationalNotificationType.SUCCESS_OVERDUE,
    }


def test_log_notifications_are_persistent_and_deduplicated(db_session, tmp_path, caplog) -> None:
    failed = _run(
        db_session,
        status=PipelineRunStatus.FAILED,
        started_at=NOW - timedelta(minutes=5),
        error_message="controlled failure",
    )
    service = OperationalNotificationService(
        db_session, _settings(tmp_path), logging.getLogger("monitor-test")
    )
    with caplog.at_level(logging.WARNING):
        first = service.run("APSC", evaluated_at=NOW)
        second = service.run("APSC", evaluated_at=NOW)
    assert first.notifications_created == 1
    assert first.deliveries_failed == 0
    assert second.notifications_created == 0
    assert second.notifications_deduplicated == 1
    event = db_session.scalar(select(OperationalNotificationEvent))
    assert event.pipeline_run_id == failed.id
    assert event.delivery_status == OperationalNotificationDeliveryStatus.DELIVERED
    assert "controlled failure" not in event.message
    assert "operational_notification" in caplog.text


def test_file_routing_is_canonical_and_dry_run_writes_nothing(db_session, tmp_path) -> None:
    _run(
        db_session,
        status=PipelineRunStatus.FAILED,
        started_at=NOW - timedelta(minutes=5),
    )
    output = tmp_path / "notifications" / "events.jsonl"
    settings = _settings(
        tmp_path,
        monitor_notification_channels="FILE,LOG,FILE",
        monitor_notification_file=str(output),
    )
    service = OperationalNotificationService(db_session, settings, logging.getLogger(__name__))
    preview = service.run("APSC", dry_run=True, evaluated_at=NOW)
    assert preview.alerts_detected == 1
    assert preview.notifications_created == 0
    assert not output.exists()
    assert db_session.scalar(select(func.count()).select_from(OperationalNotificationEvent)) == 0

    result = service.run("APSC", evaluated_at=NOW)
    assert result.notifications_created == 2
    payload = json.loads(output.read_text(encoding="utf-8").strip())
    assert payload["source_code"] == "APSC"
    assert payload["event_type"] == "PIPELINE_FAILED"
    assert "deduplication_key" not in payload


def test_delivery_failure_is_bounded_redacted_and_contains_no_stack_trace(
    monkeypatch, db_session, tmp_path
) -> None:
    _run(
        db_session,
        status=PipelineRunStatus.FAILED,
        started_at=NOW - timedelta(minutes=5),
    )
    service = OperationalNotificationService(
        db_session, _settings(tmp_path), logging.getLogger(__name__)
    )

    def fail_delivery(_event) -> None:
        raise OSError("postgresql://operator:secret@localhost/db failed\nTraceback: hidden")

    monkeypatch.setattr(service.router, "deliver", fail_delivery)
    summary = service.run("APSC", evaluated_at=NOW)
    event = db_session.scalar(select(OperationalNotificationEvent))
    assert summary.deliveries_failed == 1
    assert event.delivery_status == OperationalNotificationDeliveryStatus.FAILED
    assert "secret" not in event.delivery_error
    assert "Traceback" not in event.delivery_error
    assert len(event.delivery_error) <= 2000


def test_notification_database_identity_is_unique(db_session) -> None:
    common = {
        "source_code": "APSC",
        "pipeline_run_id": None,
        "event_type": OperationalNotificationType.SUCCESS_OVERDUE,
        "severity": OperationalNotificationSeverity.WARNING,
        "channel": OperationalNotificationChannel.LOG,
        "deduplication_key": "a" * 64,
        "message": "Controlled overdue alert.",
        "delivery_status": OperationalNotificationDeliveryStatus.DELIVERED,
        "delivered_at": NOW,
    }
    db_session.add(OperationalNotificationEvent(**common))
    db_session.commit()
    db_session.add(OperationalNotificationEvent(**common))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_operational_api_and_private_page_are_read_only_and_escape_failures(
    client, db_session, tmp_path
) -> None:
    failed = _run(
        db_session,
        status=PipelineRunStatus.FAILED,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        error_message="<script>alert('unsafe')</script>",
    )
    OperationalNotificationService(
        db_session, _settings(tmp_path), logging.getLogger(__name__)
    ).run("APSC", evaluated_at=datetime.now(UTC))
    before = db_session.scalar(select(func.count()).select_from(OperationalNotificationEvent))

    response = client.get("/api/v1/operational-status/apsc")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "FAILED"
    assert payload["last_failed_run"]["id"] == str(failed.id)
    assert payload["pipeline_runs_url"].endswith("source=APSC")
    events = client.get(
        "/api/v1/operational-notifications",
        params={"source": "apsc", "event_type": "PIPELINE_FAILED"},
    )
    assert events.status_code == 200
    assert len(events.json()) == 1

    page = client.get("/operations?source=APSC")
    assert page.status_code == 200
    assert "Operational Monitoring" in page.text
    assert str(failed.id) in page.text
    assert "Bounded actions" in page.text
    assert "Run all enabled" in page.text
    assert "ASDMA_ASSAM" in page.text
    assert "HIGH_PRIORITY · priority 10 · every 360 minutes" in page.text
    assert "Next due" in page.text
    assert "Last attempted" in page.text
    assert "&lt;script&gt;" in page.text
    assert "<script>alert" not in page.text
    assert client.get("/operations/unknown").status_code == 404
    after = db_session.scalar(select(func.count()).select_from(OperationalNotificationEvent))
    assert before == after


def test_operations_action_requires_same_origin_and_uses_bounded_scheduler(
    monkeypatch, client, db_session
) -> None:
    calls = []

    class StubScheduler:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self, selection, **kwargs):
            calls.append((selection, kwargs))
            return SchedulerSummary(selection, kwargs["dry_run"], ("APSC",))

    monkeypatch.setattr("app.operations_web.router.SourceSchedulerService", StubScheduler)
    rejected = client.post("/operations/actions", data={"action": "DUE", "dry_run": "true"})
    accepted = client.post(
        "/operations/actions",
        data={"action": "DUE", "dry_run": "true", "command": "ignored"},
        headers={"origin": "http://testserver", "sec-fetch-site": "same-origin"},
    )

    assert rejected.status_code == 403
    assert calls == [
        (
            SchedulerSelection.DUE,
            {
                "source": None,
                "group": None,
                "dry_run": True,
                "trigger_type": PipelineTriggerType.MANUAL,
            },
        )
    ]
    assert accepted.status_code == 200
    assert "Multi-source scheduler" in accepted.text
    assert "Selected: APSC" in accepted.text
    assert db_session.scalar(select(func.count()).select_from(PipelineRun)) == 0


def test_monitoring_cli_dry_run_has_no_notification_mutation(
    monkeypatch, capsys, db_session, tmp_path
) -> None:
    _run(
        db_session,
        status=PipelineRunStatus.FAILED,
        started_at=NOW - timedelta(minutes=5),
    )

    @contextmanager
    def session_context():
        yield db_session

    monkeypatch.setattr(monitoring_command, "SessionLocal", session_context)
    monkeypatch.setattr(monitoring_command, "get_settings", lambda: _settings(tmp_path))
    assert monitoring_command.main(["--source", "APSC", "--dry-run"]) == 0
    assert "Alerts detected:" in capsys.readouterr().out
    assert db_session.scalar(select(func.count()).select_from(OperationalNotificationEvent)) == 0
