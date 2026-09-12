import json
import uuid
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.candidates import CandidateValueType
from app.models.confidence import ReviewPriority
from app.models.review import ReviewCaseStatus, ReviewDecisionType
from app.review_web.services import ReviewCaseViewService
from app.schemas.review import ReviewDecisionCreate
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.review import ReviewService

router = APIRouter(prefix="/review", tags=["review-web"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
DatabaseSession = Annotated[Session, Depends(get_db)]


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


def _transport_value(value_type: CandidateValueType, raw: str | None) -> Any:
    if value_type == CandidateValueType.NULL:
        return None
    if raw is None:
        raise ValueError("A corrected value is required")
    if value_type == CandidateValueType.INTEGER:
        try:
            return int(raw)
        except ValueError as error:
            raise ValueError("Corrected INTEGER value must be a whole number") from error
    if value_type == CandidateValueType.BOOLEAN:
        if raw not in {"true", "false"}:
            raise ValueError("Corrected BOOLEAN value must be true or false")
        return raw == "true"
    if value_type == CandidateValueType.JSON:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("Corrected JSON value must contain valid JSON") from error
    return raw


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
def review_case(request: Request, case_id: uuid.UUID, session: DatabaseSession) -> HTMLResponse:
    try:
        view = ReviewCaseViewService(session).case(case_id)
    except ResourceNotFoundError as error:
        return _error_page(request, str(error), 404)
    except DomainConflictError as error:
        return _error_page(request, str(error), 409)
    return _template(
        request,
        "review/case.html",
        {
            "title": f"Review {view['candidate']['candidate_key']}",
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
        corrected_type = None
        corrected_value = None
        if decision == ReviewDecisionType.CORRECT_AND_APPROVE:
            corrected_type = item.candidate_value_type_snapshot
            if corrected_type is None:
                raise ValueError("Revision items cannot be corrected")
            corrected_value = _transport_value(corrected_type, form.get("corrected_value"))
        payload = ReviewDecisionCreate(
            decision=decision,
            reviewer_identifier=form.get("reviewer_identifier", ""),
            decision_note=form.get("decision_note") or None,
            corrected_value_type=corrected_type,
            corrected_value=corrected_value,
            evidence_note=form.get("evidence_note") or None,
        )
        service.decide_item(item_id, payload)
    except (ValueError, ValidationError, DomainConflictError) as error:
        message = str(error)
        if isinstance(error, ValidationError):
            message = "; ".join(item["msg"] for item in error.errors())
        return _case_redirect(case_id, error=message)
    return _case_redirect(case_id, message="Decision recorded")
