import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.confidence import ReviewPriority
from app.models.review import ReviewCaseStatus, ReviewDecisionType
from app.review_web.services import ReviewCaseViewService
from app.schemas.review import ReviewDecisionCreate
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.review import ReviewService

router = APIRouter(prefix="/review", tags=["review-web"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
DatabaseSession = Annotated[Session, Depends(get_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]


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


def _error_page(request: Request, message: str, status_code: int) -> HTMLResponse:
    return _template(
        request,
        "review/error.html",
        {"title": "Review error", "error": message},
        status_code=status_code,
    )


def _case_redirect(
    case_id: uuid.UUID,
    *,
    message: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    notices = {"message": message, "error": error}
    query = urlencode({key: value for key, value in notices.items() if value})
    suffix = f"?{query}" if query else ""
    return RedirectResponse(f"/review/cases/{case_id}{suffix}", status_code=303)


async def _read_form(request: Request) -> dict[str, str]:
    body = await request.body()
    if len(body) > 65_536:
        raise ValueError("Form submission is too large")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise ValueError("Only standard URL-encoded form submissions are accepted")
    values = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=False)
    return {key: items[-1] for key, items in values.items()}


@router.get("", response_class=HTMLResponse, name="review_queue")
def review_queue(
    request: Request,
    session: DatabaseSession,
    status: str | None = None,
    priority: str | None = None,
) -> HTMLResponse:
    try:
        status_filter = ReviewCaseStatus(status) if status else None
        priority_filter = ReviewPriority(priority) if priority else None
    except ValueError:
        return _error_page(request, "Invalid review queue filter", 400)
    view = ReviewCaseViewService(session).queue(status=status_filter, priority=priority_filter)
    return _template(
        request,
        "review/queue.html",
        {
            "title": "Human Review Queue",
            **view,
            "selected_status": status or "",
            "selected_priority": priority or "",
            "statuses": [item.value for item in ReviewCaseStatus],
            "priorities": [item.value for item in ReviewPriority],
        },
    )


@router.get("/cases/{case_id}", response_class=HTMLResponse, name="review_case")
def review_case(
    request: Request,
    case_id: uuid.UUID,
    session: DatabaseSession,
    post: str | None = None,
) -> HTMLResponse:
    try:
        view = ReviewCaseViewService(session).case(case_id, focus_post_key=post)
    except ResourceNotFoundError as error:
        return _error_page(request, str(error), 404)
    except DomainConflictError as error:
        return _error_page(request, str(error), 409)
    focus_name = (view["focused_post"] or {}).get(
        "name", view["candidate"]["candidate_key"]
    )
    return _template(
        request,
        "review/case.html",
        {
            "title": f"Review {focus_name}",
            **view,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/cases/{case_id}/start")
def start_case(case_id: uuid.UUID, session: DatabaseSession) -> RedirectResponse:
    try:
        ReviewService(session).start_case(case_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        return _case_redirect(case_id, error=str(error))
    return _case_redirect(case_id, message="Review started")


@router.post("/cases/{case_id}/cancel")
def cancel_case(case_id: uuid.UUID, session: DatabaseSession) -> RedirectResponse:
    try:
        ReviewService(session).cancel_case(case_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        return _case_redirect(case_id, error=str(error))
    return _case_redirect(case_id, message="Review case cancelled")


@router.post("/items/{item_id}/decision")
async def decide_item(
    request: Request,
    item_id: uuid.UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> HTMLResponse:
    service = ReviewService(session)
    try:
        item = service.get_item(item_id)
    except ResourceNotFoundError as error:
        return _error_page(request, str(error), 404)
    case_id = item.review_case_id
    try:
        form = await _read_form(request)
        decision = ReviewDecisionType(form.get("decision", ""))
        if decision not in {ReviewDecisionType.APPROVE_AS_IS, ReviewDecisionType.REJECT}:
            raise ValueError("The local review page supports only Approve or Reject")
        comment = (form.get("decision_note") or "").strip()
        if not comment:
            raise ValueError("A review comment is required")
        payload = ReviewDecisionCreate(
            decision=decision,
            reviewer_identifier=settings.review_web_reviewer_identifier,
            decision_note=comment,
        )
        service.decide_item(item_id, payload)
    except (ValueError, ValidationError, DomainConflictError) as error:
        message = str(error)
        if isinstance(error, ValidationError):
            message = "; ".join(item["msg"] for item in error.errors())
        return _case_redirect(case_id, error=message)
    return _case_redirect(case_id, message="Decision recorded")
