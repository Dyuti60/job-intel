import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.monitoring import OperationalNotificationDeliveryStatus
from app.services.operational_monitoring import (
    OperationalMonitoringService,
    OperationalNotificationService,
)

router = APIRouter(prefix="/operations", tags=["operations-web"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("", response_class=HTMLResponse, name="operations_status")
def operations_status(
    request: Request,
    session: DatabaseSession,
    source: str | None = None,
) -> HTMLResponse:
    settings = get_settings()
    monitoring = OperationalMonitoringService(session, settings)
    sources = monitoring.source_codes()
    if source:
        try:
            selected = [source.strip().upper()]
            health = [monitoring.evaluate(selected[0])]
        except ValueError as error:
            return templates.TemplateResponse(
                request=request,
                name="operations/error.html",
                context={"request": request, "title": "Operational error", "error": str(error)},
                status_code=422,
            )
    else:
        selected = sources
        health = [monitoring.evaluate(item) for item in sources]
    notifications = OperationalNotificationService(
        session,
        settings,
        logging.getLogger(__name__),
    ).list_events(
        source_code=selected[0] if len(selected) == 1 else None,
        event_type=None,
        channel=None,
        delivery_status=None,
        offset=0,
        limit=50,
    )
    return templates.TemplateResponse(
        request=request,
        name="operations/status.html",
        context={
            "request": request,
            "title": "Operational Monitoring",
            "sources": sources,
            "selected_source": source or "",
            "health_records": health,
            "notifications": notifications,
            "failed_delivery_count": sum(
                event.delivery_status == OperationalNotificationDeliveryStatus.FAILED
                for event in notifications
            ),
        },
    )
