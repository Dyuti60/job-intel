from sqlalchemy import Select, distinct, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.monitoring import (
    OperationalNotificationChannel,
    OperationalNotificationDeliveryStatus,
    OperationalNotificationEvent,
    OperationalNotificationType,
)
from app.models.pipeline import PipelineRun, PipelineRunStatus, PipelineStageRun


class OperationalMonitoringRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def source_codes(self) -> list[str]:
        return list(
            self.session.scalars(
                select(distinct(PipelineRun.source_code)).order_by(PipelineRun.source_code)
            )
        )

    def runs_for_source(self, source_code: str, *, limit: int = 500) -> list[PipelineRun]:
        return list(
            self.session.scalars(
                select(PipelineRun)
                .options(selectinload(PipelineRun.stages))
                .where(PipelineRun.source_code == source_code)
                .order_by(PipelineRun.started_at.desc(), PipelineRun.id.desc())
                .limit(limit)
            )
        )

    def current_runs_for_source(self, source_code: str) -> list[PipelineRun]:
        return list(
            self.session.scalars(
                select(PipelineRun)
                .where(
                    PipelineRun.source_code == source_code,
                    PipelineRun.status == PipelineRunStatus.RUNNING,
                )
                .order_by(PipelineRun.started_at.desc(), PipelineRun.id.desc())
            )
        )

    def stage_runs_for_source(
        self, source_code: str, *, stage: str, limit: int
    ) -> list[PipelineStageRun]:
        return list(
            self.session.scalars(
                select(PipelineStageRun)
                .join(PipelineRun, PipelineRun.id == PipelineStageRun.pipeline_run_id)
                .where(
                    PipelineRun.source_code == source_code,
                    PipelineStageRun.stage == stage,
                )
                .order_by(PipelineStageRun.completed_at.desc(), PipelineStageRun.id.desc())
                .limit(limit)
            )
        )


class OperationalNotificationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, event: OperationalNotificationEvent) -> None:
        self.session.add(event)

    def add_if_absent(self, event: OperationalNotificationEvent) -> bool:
        savepoint = self.session.begin_nested()
        try:
            self.session.add(event)
            self.session.flush()
        except IntegrityError:
            savepoint.rollback()
            return False
        savepoint.commit()
        return True

    def get_by_deduplication_key(self, key: str) -> OperationalNotificationEvent | None:
        return self.session.scalar(
            select(OperationalNotificationEvent).where(
                OperationalNotificationEvent.deduplication_key == key
            )
        )

    def list(
        self,
        *,
        source_code: str | None,
        event_type: OperationalNotificationType | None,
        channel: OperationalNotificationChannel | None,
        delivery_status: OperationalNotificationDeliveryStatus | None,
        offset: int,
        limit: int,
    ) -> list[OperationalNotificationEvent]:
        statement: Select[tuple[OperationalNotificationEvent]] = select(
            OperationalNotificationEvent
        ).order_by(
            OperationalNotificationEvent.created_at.desc(),
            OperationalNotificationEvent.id.desc(),
        )
        if source_code is not None:
            statement = statement.where(
                OperationalNotificationEvent.source_code == source_code
            )
        if event_type is not None:
            statement = statement.where(OperationalNotificationEvent.event_type == event_type)
        if channel is not None:
            statement = statement.where(OperationalNotificationEvent.channel == channel)
        if delivery_status is not None:
            statement = statement.where(
                OperationalNotificationEvent.delivery_status == delivery_status
            )
        return list(self.session.scalars(statement.offset(offset).limit(limit)))
