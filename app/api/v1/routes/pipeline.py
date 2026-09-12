import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.pipeline import PipelineRunStatus, PipelineTriggerType
from app.schemas.pipeline import PipelineRunDetail, PipelineRunSummary
from app.services.exceptions import ResourceNotFoundError
from app.services.pipeline_history import PipelineHistoryService

router = APIRouter(tags=["pipeline operations"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("/pipeline-runs", response_model=list[PipelineRunSummary])
def list_pipeline_runs(
    session: DatabaseSession,
    source: str | None = None,
    status_filter: Annotated[PipelineRunStatus | None, Query(alias="status")] = None,
    trigger_type: PipelineTriggerType | None = None,
    dry_run: bool | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[PipelineRunSummary]:
    runs = PipelineHistoryService(session).list(
        source_code=source,
        status=status_filter,
        trigger_type=trigger_type,
        dry_run=dry_run,
        offset=offset,
        limit=limit,
    )
    return [PipelineRunSummary.model_validate(item) for item in runs]


@router.get("/pipeline-runs/{pipeline_run_id}", response_model=PipelineRunDetail)
def get_pipeline_run(pipeline_run_id: uuid.UUID, session: DatabaseSession) -> PipelineRunDetail:
    try:
        pipeline_run = PipelineHistoryService(session).get(pipeline_run_id)
    except ResourceNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return PipelineRunDetail.model_validate(pipeline_run)
