import enum
import logging
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.monitoring import OperationalNotificationDeliveryStatus
from app.models.pipeline import PipelineTriggerType
from app.models.source_registry import SourceScheduleGroup
from app.services.master_publisher_worker import (
    MasterPublisherWorkerService,
    format_master_publisher_summary,
)
from app.services.operational_monitoring import (
    OperationalMonitoringService,
    OperationalNotificationService,
)
from app.services.source_scheduler import (
    SchedulerSelection,
    SourceSchedulerService,
    format_scheduler_summary,
    source_schedule_catalog,
    source_schedule_previews,
)

router = APIRouter(prefix="/operations", tags=["operations-web"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
DatabaseSession = Annotated[Session, Depends(get_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


class OperationAction(enum.StrEnum):
    SOURCE = "SOURCE"
    GROUP = "GROUP"
    DUE = "DUE"
    ALL_ENABLED = "ALL_ENABLED"
    PUBLISHER = "PUBLISHER"
    MONITOR = "MONITOR"


def _template(
    request: Request,
    name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={"request": request, **context},
        status_code=status_code,
    )


def _error_page(request: Request, error: str, status_code: int) -> HTMLResponse:
    return _template(
        request,
        "operations/error.html",
        {"title": "Operational error", "error": error},
        status_code=status_code,
    )


def _source_codes(monitoring: OperationalMonitoringService) -> list[str]:
    return sorted(set(monitoring.source_codes()) | set(source_schedule_catalog()))


def _status_context(
    session: Session,
    settings: Settings,
    *,
    source: str | None,
    operation_result: str | None = None,
) -> dict[str, Any]:
    monitoring = OperationalMonitoringService(session, settings)
    sources = _source_codes(monitoring)
    if source:
        selected = [source.strip().upper()]
        health = [monitoring.evaluate(selected[0])]
    else:
        selected = sources
        health = [monitoring.evaluate(item) for item in sources]
    scheduled = tuple(code for code in selected if code in source_schedule_catalog())
    schedule_previews = {
        item.source_code: item for item in source_schedule_previews(session, scheduled)
    }
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
    return {
        "title": "Operational Monitoring",
        "sources": sources,
        "selected_source": source or "",
        "schedule_groups": [item.value for item in SourceScheduleGroup],
        "health_records": health,
        "schedule_previews": schedule_previews,
        "notifications": notifications,
        "operation_result": operation_result,
        "failed_delivery_count": sum(
            event.delivery_status == OperationalNotificationDeliveryStatus.FAILED
            for event in notifications
        ),
    }


async def _read_same_origin_form(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin")
    expected = urlsplit(str(request.base_url))
    supplied = urlsplit(origin or "")
    if (
        not origin
        or supplied.scheme != expected.scheme
        or supplied.netloc != expected.netloc
        or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"
    ):
        raise PermissionError("A same-origin browser submission is required")
    body = await request.body()
    if len(body) > 65_536:
        raise ValueError("Form submission is too large")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise ValueError("Only standard URL-encoded form submissions are accepted")
    values = parse_qs(
        body.decode("utf-8"),
        keep_blank_values=True,
        strict_parsing=False,
        max_num_fields=64,
    )
    return {key: items[-1] for key, items in values.items()}


@router.get("", response_class=HTMLResponse, name="operations_status")
def operations_status(
    request: Request,
    session: DatabaseSession,
    settings: ApplicationSettings,
    source: str | None = None,
) -> HTMLResponse:
    try:
        context = _status_context(session, settings, source=source)
    except ValueError as error:
        return _error_page(request, str(error), 422)
    return _template(request, "operations/status.html", context)


@router.post("/actions", response_class=HTMLResponse, name="operations_action")
async def operations_action(
    request: Request,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> HTMLResponse:
    try:
        form = await _read_same_origin_form(request)
    except PermissionError as error:
        return _error_page(request, str(error), 403)
    try:
        action = OperationAction(form.get("action", ""))
        source = form.get("source", "").strip().upper() or None
        group_value = form.get("group", "").strip().upper()
        dry_run = form.get("dry_run") == "true"
        logger = logging.getLogger(__name__)
        if action in {
            OperationAction.SOURCE,
            OperationAction.GROUP,
            OperationAction.DUE,
            OperationAction.ALL_ENABLED,
        }:
            selection = {
                OperationAction.SOURCE: SchedulerSelection.SOURCE,
                OperationAction.GROUP: SchedulerSelection.GROUP,
                OperationAction.DUE: SchedulerSelection.DUE,
                OperationAction.ALL_ENABLED: SchedulerSelection.ALL,
            }[action]
            group = SourceScheduleGroup(group_value) if action == OperationAction.GROUP else None
            summary = SourceSchedulerService(session, settings, logger).run(
                selection,
                source=source,
                group=group,
                dry_run=dry_run,
                trigger_type=PipelineTriggerType.MANUAL,
            )
            result = format_scheduler_summary(summary)
        elif action == OperationAction.PUBLISHER:
            summary = MasterPublisherWorkerService(session, logger).run(
                batch_size=settings.master_publisher_batch_size,
                dry_run=dry_run,
            )
            result = format_master_publisher_summary(summary)
        else:
            if source is None or source not in source_schedule_catalog():
                raise ValueError("A supported source is required for monitoring")
            summary = OperationalNotificationService(session, settings, logger).run(
                source,
                dry_run=dry_run,
            )
            result = (
                f"Monitoring {summary.source_code}: health={summary.status.value}, "
                f"alerts={summary.alerts_detected}, created={summary.notifications_created}, "
                f"deduplicated={summary.notifications_deduplicated}, "
                f"delivery_failures={summary.deliveries_failed}, dry_run={summary.dry_run}"
            )
        context = _status_context(session, settings, source=source, operation_result=result)
        return _template(request, "operations/status.html", context)
    except ValueError as error:
        session.rollback()
        return _error_page(request, str(error)[:1000], 400)
    except (SQLAlchemyError, OSError, RuntimeError):
        session.rollback()
        logging.getLogger(__name__).exception("bounded_operation_failed")
        return _error_page(
            request,
            "The bounded operation failed. Inspect private application logs and run history.",
            500,
        )
