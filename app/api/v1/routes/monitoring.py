import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.monitoring import (
    OperationalNotificationChannel,
    OperationalNotificationDeliveryStatus,
    OperationalNotificationType,
)
from app.schemas.monitoring import (
    OperationalNotificationRead,
    SourceOperationalHealthRead,
)
from app.services.operational_monitoring import (
    OperationalMonitoringService,
    OperationalNotificationService,
)

router = APIRouter(tags=["operational monitoring"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get(
    "/operational-status/{source_code}",
    response_model=SourceOperationalHealthRead,
)
def get_operational_status(
    source_code: str,
    session: DatabaseSession,
) -> SourceOperationalHealthRead:
    try:
        health = OperationalMonitoringService(session, get_settings()).evaluate(source_code)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    return SourceOperationalHealthRead.model_validate(health)


@router.get(
    "/operational-notifications",
    response_model=list[OperationalNotificationRead],
)
def list_operational_notifications(
    session: DatabaseSession,
    source: str | None = None,
    event_type: OperationalNotificationType | None = None,
    channel: OperationalNotificationChannel | None = None,
    delivery_status: OperationalNotificationDeliveryStatus | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[OperationalNotificationRead]:
    try:
        events = OperationalNotificationService(
            session,
            get_settings(),
            logging.getLogger(__name__),
        ).list_events(
            source_code=source,
            event_type=event_type,
            channel=channel,
            delivery_status=delivery_status,
            offset=offset,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    return [OperationalNotificationRead.model_validate(event) for event in events]
