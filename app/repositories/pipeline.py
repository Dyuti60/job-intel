import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.models.pipeline import PipelineRun, PipelineRunStatus, PipelineTriggerType


class PipelineRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, pipeline_run: PipelineRun) -> None:
        self.session.add(pipeline_run)

    def get(self, pipeline_run_id: uuid.UUID) -> PipelineRun | None:
        return self.session.scalar(
            select(PipelineRun)
            .execution_options(populate_existing=True)
            .options(selectinload(PipelineRun.stages))
            .where(PipelineRun.id == pipeline_run_id)
        )

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
        statement: Select[tuple[PipelineRun]] = select(PipelineRun).order_by(
            PipelineRun.started_at.desc(), PipelineRun.id.desc()
        )
        if source_code is not None:
            statement = statement.where(PipelineRun.source_code == source_code)
        if status is not None:
            statement = statement.where(PipelineRun.status == status)
        if trigger_type is not None:
            statement = statement.where(PipelineRun.trigger_type == trigger_type)
        if dry_run is not None:
            statement = statement.where(PipelineRun.dry_run == dry_run)
        return list(self.session.scalars(statement.offset(offset).limit(limit)))
