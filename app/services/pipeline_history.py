import dataclasses
import enum
import json
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.pipeline import (
    PipelineRun,
    PipelineRunStatus,
    PipelineStage,
    PipelineStageRun,
    PipelineStageStatus,
    PipelineTriggerType,
)
from app.repositories.pipeline import PipelineRunRepository
from app.services.exceptions import ResourceNotFoundError
from app.services.pipeline_orchestrator import (
    PipelineOrchestratorService,
    PipelineStatus,
    PipelineSummary,
)

MAX_ERROR_MESSAGE_LENGTH = 2000
_CREDENTIAL_URL = re.compile(r"(\w+://)[^\s:/]+:[^\s@]+@")


def _bounded_error(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = _CREDENTIAL_URL.sub(r"\1***:***@", value).strip()
    return redacted[:MAX_ERROR_MESSAGE_LENGTH]


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    raise TypeError(f"Unsupported summary value: {type(value).__name__}")


def pipeline_summary_json(summary: PipelineSummary) -> dict[str, Any]:
    payload = json.loads(json.dumps(dataclasses.asdict(summary), default=_json_default))
    payload["errors"] = [_bounded_error(item) for item in payload.get("errors", [])]
    for stage in payload.get("stage_executions", []):
        stage["error_message"] = _bounded_error(stage.get("error_message"))
    verification = payload.get("verification")
    if verification:
        verification["errors"] = [
            _bounded_error(item) for item in verification.get("errors", [])
        ]
    return payload


class PipelineHistoryService:
    """Persist an operational projection around the authoritative T-013 orchestrator."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = PipelineRunRepository(session)

    def execute(
        self,
        orchestrator: PipelineOrchestratorService,
        *,
        source: str,
        dry_run: bool,
        trigger_type: PipelineTriggerType,
        discovery_adapter: Any = None,
    ) -> tuple[PipelineSummary, PipelineRun]:
        source_code = source.strip().upper()
        started_at = datetime.now(UTC)
        pipeline_run = PipelineRun(
            source_code=source_code,
            authority_code=source_code,
            trigger_type=trigger_type,
            status=PipelineRunStatus.RUNNING,
            dry_run=dry_run,
            started_at=started_at,
            summary_json={},
        )
        self.repository.add(pipeline_run)
        self.session.commit()
        run_id = pipeline_run.id

        try:
            summary = orchestrator.run(
                source=source_code,
                dry_run=dry_run,
                discovery_adapter=discovery_adapter,
            )
        except Exception as error:
            self.session.rollback()
            summary = PipelineSummary(
                source=source_code,
                authority_code=source_code,
                dry_run=dry_run,
                status=PipelineStatus.FAILED,
                errors=[f"Pipeline failed: {type(error).__name__}: {_bounded_error(str(error))}"],
            )

        pipeline_run = self.repository.get(run_id)
        if pipeline_run is None:
            raise RuntimeError("Pipeline history record disappeared during execution")
        completed_at = datetime.now(UTC)
        pipeline_run.authority_code = summary.authority_code
        pipeline_run.status = PipelineRunStatus(summary.status.value)
        pipeline_run.completed_at = completed_at
        pipeline_run.duration_ms = max(0, round((completed_at - started_at).total_seconds() * 1000))
        pipeline_run.review_cases_queued = (
            summary.verification.review_cases_queued if summary.verification else 0
        )
        if summary.publisher:
            pipeline_run.masters_created = summary.publisher.master_created
            pipeline_run.masters_updated = summary.publisher.master_updated
            pipeline_run.masters_unchanged = summary.publisher.master_unchanged
        pipeline_run.summary_json = pipeline_summary_json(summary)

        for execution in summary.stage_executions:
            stage = PipelineStage(execution.stage)
            stage_status = PipelineStageStatus(execution.status)
            stage_run = PipelineStageRun(
                pipeline_run_id=run_id,
                stage=stage,
                status=stage_status,
                started_at=execution.started_at,
                completed_at=execution.completed_at,
                duration_ms=execution.duration_ms,
                summary_json=execution.summary,
                error_code=(execution.error_code or "")[:128] or None,
                error_message=_bounded_error(execution.error_message),
            )
            self.session.add(stage_run)
            if stage == PipelineStage.DISCOVERY:
                pipeline_run.discovery_status = stage_status
            elif stage == PipelineStage.VERIFICATION:
                pipeline_run.verification_status = stage_status
            else:
                pipeline_run.publisher_status = stage_status

        failed_stage = next(
            (
                execution
                for execution in reversed(summary.stage_executions)
                if execution.status == PipelineStageStatus.FAILED.value
            ),
            None,
        )
        if failed_stage is not None:
            pipeline_run.error_stage = PipelineStage(failed_stage.stage)
            pipeline_run.error_code = (failed_stage.error_code or "PIPELINE_STAGE_FAILED")[:128]
            pipeline_run.error_message = _bounded_error(failed_stage.error_message)
        elif summary.errors:
            pipeline_run.error_code = "PIPELINE_FAILED"
            pipeline_run.error_message = _bounded_error(summary.errors[0])

        self.session.commit()
        refreshed = self.repository.get(run_id)
        if refreshed is None:
            raise RuntimeError("Completed PipelineRun could not be reloaded")
        return summary, refreshed

    def get(self, pipeline_run_id: uuid.UUID) -> PipelineRun:
        pipeline_run = self.repository.get(pipeline_run_id)
        if pipeline_run is None:
            raise ResourceNotFoundError(f"PipelineRun {pipeline_run_id} was not found")
        return pipeline_run

    def list(
        self,
        *,
        source_code: str | None,
        status: PipelineRunStatus | None,
        trigger_type: PipelineTriggerType | None,
        dry_run: bool | None,
        offset: int,
        limit: int,
    ) -> list[PipelineRun]:
        normalized_source = source_code.strip().upper() if source_code else None
        return self.repository.list(
            source_code=normalized_source,
            status=status,
            trigger_type=trigger_type,
            dry_run=dry_run,
            offset=offset,
            limit=limit,
        )
