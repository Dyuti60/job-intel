from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models.pipeline import (
    PipelineRun,
    PipelineRunStatus,
    PipelineStage,
    PipelineStageStatus,
    PipelineTriggerType,
)
from app.models.source_registry import AuthorityStatus, AuthorityType, RecruitingAuthority
from app.services.apsc_discovery import DiscoverySummary
from app.services.master_publisher_worker import MasterPublisherWorkerSummary
from app.services.pipeline_history import MAX_ERROR_MESSAGE_LENGTH, PipelineHistoryService
from app.services.pipeline_orchestrator import (
    PipelineStageExecution,
    PipelineStatus,
    PipelineSummary,
)
from app.services.verification_worker import VerificationWorkerSummary


def _stage(stage: str, status: str, *, error: str | None = None) -> PipelineStageExecution:
    started = datetime.now(UTC)
    return PipelineStageExecution(
        stage=stage,
        status=status,
        started_at=started,
        completed_at=started + timedelta(milliseconds=4),
        duration_ms=4,
        summary={"stage": stage.lower()},
        error_code="ControlledError" if error else None,
        error_message=error,
    )


def _summary(status: PipelineStatus = PipelineStatus.SUCCESS) -> PipelineSummary:
    discovery_status = "PARTIAL" if status == PipelineStatus.PARTIAL else "SUCCESS"
    return PipelineSummary(
        source="APSC",
        authority_code="APSC",
        dry_run=False,
        status=status,
        discovery=DiscoverySummary(
            run_id="controlled",
            status=discovery_status,
            documents_new=1,
            documents_changed=0,
            documents_unchanged=0,
            candidates_created=1,
            candidates_reused=0,
            revisions_created=1,
            revisions_reused=0,
            fields_extracted=3,
            evidence_records=3,
            warnings=(),
            dry_run=False,
        ),
        verification=VerificationWorkerSummary(
            authority="APSC", dry_run=False, completed=1, review_cases_queued=1
        ),
        publisher=MasterPublisherWorkerSummary(
            dry_run=False, master_created=1, master_updated=2, master_unchanged=3
        ),
        active_review_cases=1,
        stage_executions=[
            _stage("DISCOVERY", discovery_status),
            _stage("VERIFICATION", "SUCCESS"),
            _stage("MASTER_PUBLISHER", "SUCCESS"),
        ],
    )


class StubOrchestrator:
    def __init__(self, summary: PipelineSummary) -> None:
        self.summary = summary

    def run(self, **_kwargs) -> PipelineSummary:
        return self.summary


def _execute(db_session, summary: PipelineSummary, *, dry_run: bool = False):
    summary.dry_run = dry_run
    return PipelineHistoryService(db_session).execute(
        StubOrchestrator(summary),
        source="APSC",
        dry_run=dry_run,
        trigger_type=PipelineTriggerType.CLI,
    )


def test_successful_and_partial_pipeline_history_records_stages(db_session) -> None:
    _, successful = _execute(db_session, _summary())
    assert successful.status == PipelineRunStatus.SUCCESS
    assert successful.discovery_status == PipelineStageStatus.SUCCESS
    assert successful.verification_status == PipelineStageStatus.SUCCESS
    assert successful.publisher_status == PipelineStageStatus.SUCCESS
    assert successful.completed_at is not None
    assert successful.duration_ms >= 0
    assert successful.review_cases_queued == 1
    master_counts = (
        successful.masters_created,
        successful.masters_updated,
        successful.masters_unchanged,
    )
    assert master_counts == (
        1,
        2,
        3,
    )
    assert {stage.stage for stage in successful.stages} == {
        PipelineStage.DISCOVERY,
        PipelineStage.VERIFICATION,
        PipelineStage.MASTER_PUBLISHER,
    }
    assert all(stage.duration_ms == 4 for stage in successful.stages)
    assert successful.summary_json["status"] == "SUCCESS"

    _, partial = _execute(db_session, _summary(PipelineStatus.PARTIAL))
    assert partial.status == PipelineRunStatus.PARTIAL
    assert partial.discovery_status == PipelineStageStatus.PARTIAL


def test_failed_discovery_is_finalized_and_error_is_bounded_and_redacted(db_session) -> None:
    secret_error = "postgresql://operator:secret@localhost/db " + ("x" * 3000)
    summary = PipelineSummary(
        source="APSC",
        authority_code="APSC",
        dry_run=False,
        status=PipelineStatus.FAILED,
        errors=[f"Discovery failed: {secret_error}"],
        stage_executions=[_stage("DISCOVERY", "FAILED", error=secret_error)],
    )
    _, pipeline_run = _execute(db_session, summary)
    assert pipeline_run.status == PipelineRunStatus.FAILED
    assert pipeline_run.error_stage == PipelineStage.DISCOVERY
    assert pipeline_run.error_code == "ControlledError"
    assert len(pipeline_run.error_message) == MAX_ERROR_MESSAGE_LENGTH
    assert "secret" not in pipeline_run.error_message
    assert pipeline_run.verification_status is None
    assert pipeline_run.publisher_status is None


def test_dry_run_keeps_history_but_rolls_back_domain_mutation(db_session) -> None:
    class DryRunOrchestrator:
        def run(self, **_kwargs):
            db_session.add(
                RecruitingAuthority(
                    code="ROLLBACK_ME",
                    name="Rollback fixture",
                    authority_type=AuthorityType.OTHER,
                    official_website_url="https://example.test/",
                    status=AuthorityStatus.ACTIVE,
                )
            )
            db_session.flush()
            db_session.rollback()
            result = _summary()
            result.dry_run = True
            return result

    _, pipeline_run = PipelineHistoryService(db_session).execute(
        DryRunOrchestrator(),
        source="APSC",
        dry_run=True,
        trigger_type=PipelineTriggerType.CLI,
    )
    assert pipeline_run.dry_run is True
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(RecruitingAuthority)
            .where(RecruitingAuthority.code == "ROLLBACK_ME")
        )
        == 0
    )
    assert db_session.scalar(select(func.count()).select_from(PipelineRun)) == 1


def test_repeated_runs_create_operational_history(db_session) -> None:
    _, first = _execute(db_session, _summary())
    _, second = _execute(db_session, _summary())
    assert first.id != second.id
    assert db_session.scalar(select(func.count()).select_from(PipelineRun)) == 2


def test_pipeline_history_api_lists_filters_orders_and_gets_detail(client, db_session) -> None:
    _, first = _execute(db_session, _summary(), dry_run=True)
    first.started_at = first.started_at - timedelta(hours=1)
    db_session.commit()
    _, second = _execute(db_session, _summary())

    response = client.get("/api/v1/pipeline-runs")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(second.id), str(first.id)]
    filtered = client.get(
        "/api/v1/pipeline-runs",
        params={"source": "apsc", "status": "SUCCESS", "trigger_type": "CLI", "dry_run": True},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [str(first.id)]

    detail = client.get(f"/api/v1/pipeline-runs/{second.id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["summary_json"]["source"] == "APSC"
    assert len(payload["stages"]) == 3
    missing = client.get("/api/v1/pipeline-runs/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
