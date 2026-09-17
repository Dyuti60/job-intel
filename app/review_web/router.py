import json
import re
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
from app.models.candidates import CandidateValueType
from app.models.confidence import ReviewPriority
from app.models.review import ReviewCaseStatus, ReviewDecisionType
from app.review_web.actions import ReviewPublicationActions
from app.review_web.services import ReviewCaseViewService
from app.schemas.review import ReviewDecisionCreate
from app.services.candidate_values import normalize_typed_value
from app.services.exceptions import DomainConflictError, ResourceNotFoundError
from app.services.master import MasterPublisherService
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
    post: str | None = None,
    message: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    notices = {"post": post, "message": message, "error": error}
    query = urlencode({key: value for key, value in notices.items() if value})
    suffix = f"?{query}" if query else ""
    return RedirectResponse(f"/review/cases/{case_id}{suffix}", status_code=303)


async def _read_form(request: Request) -> dict[str, str]:
    values = await _read_form_values(request)
    return {key: items[-1] for key, items in values.items()}


async def _read_form_values(request: Request) -> dict[str, list[str]]:
    body = await request.body()
    if len(body) > 65_536:
        raise ValueError("Form submission is too large")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise ValueError("Only standard URL-encoded form submissions are accepted")
    values = parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=False)
    return values


@router.post("/bulk-publish")
async def bulk_publish(
    request: Request, session: DatabaseSession, settings: ApplicationSettings
) -> HTMLResponse:
    try:
        form = await _read_form_values(request)
        selected = form.get("selected", [])
        if not 1 <= len(selected) <= 50:
            raise ValueError("Select between 1 and 50 Posts")
        selections = []
        for value in selected:
            case, post = value.split(":", 1)
            selections.append((uuid.UUID(case), post))
        result = ReviewPublicationActions(session).bulk(
            selections,
            settings.review_web_reviewer_identifier,
            form.get("comment", [""])[-1],
        )
    except (ValueError, DomainConflictError) as error:
        return _error_page(request, str(error), 400)
    message = (
        f"{result['published']} published; {result['already_published']} already published; "
        f"{len(result['blocked'])} blocked"
    )
    return _template(
        request,
        "review/bulk_result.html",
        {
            "title": "Bulk review result",
            "message": message,
            "details": result["blocked"],
        },
    )


@router.post("/cases/{case_id}/quick-publish")
async def quick_publish(
    request: Request, case_id: uuid.UUID, session: DatabaseSession, settings: ApplicationSettings
) -> RedirectResponse:
    post = None
    try:
        form = await _read_form(request)
        post = form.get("post", "")
        ReviewPublicationActions(session).quick(
            case_id,
            post,
            settings.review_web_reviewer_identifier,
            form.get("comment", ""),
        )
        session.commit()
    except (ValueError, DomainConflictError, ResourceNotFoundError) as error:
        session.rollback()
        return _case_redirect(case_id, post=post, error=str(error))
    return _case_redirect(case_id, post=post, message="Post approved and published")


def _typed_form_value(value_type: CandidateValueType, raw_value: str) -> Any:
    if value_type == CandidateValueType.INTEGER:
        if re.fullmatch(r"-?\d+", raw_value.strip()) is None:
            raise ValueError("INTEGER values require a whole number")
        value: Any = int(raw_value)
    elif value_type == CandidateValueType.BOOLEAN:
        normalized = raw_value.strip().casefold()
        if normalized not in {"true", "false"}:
            raise ValueError("BOOLEAN values require true or false")
        value = normalized == "true"
    elif value_type == CandidateValueType.JSON:
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise ValueError("JSON values require valid JSON") from error
    elif value_type == CandidateValueType.NULL:
        value = None
    else:
        value = raw_value
    return normalize_typed_value(value_type, value)


@router.get("", response_class=HTMLResponse, name="review_queue")
def review_queue(
    request: Request,
    session: DatabaseSession,
    status: str | None = None,
    priority: str | None = None,
    q: str = "",
    page: int = 1,
    page_size: int = 25,
) -> HTMLResponse:
    if len(q) > 100 or page < 1 or not 1 <= page_size <= 50:
        return _error_page(request, "Invalid queue search or page", 400)
    try:
        status_filter = ReviewCaseStatus(status) if status else None
        priority_filter = ReviewPriority(priority) if priority else None
    except ValueError:
        return _error_page(request, "Invalid review queue filter", 400)
    view = ReviewCaseViewService(session).queue(status=status_filter, priority=priority_filter)
    rows = view["cases"]
    if q.strip():
        term = q.strip().casefold()
        rows = [
            row for row in rows if term in " ".join(
                str(row[key]) for key in (
                    "post_name", "organization", "authority_name", "advertisement_title"
                )
            ).casefold()
        ]
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = min(page, pages)
    view["cases"] = rows[(page - 1) * page_size:page * page_size]
    return _template(
        request,
        "review/queue.html",
        {
            "title": "Human Review Queue",
            **view,
            "selected_status": status or "",
            "selected_priority": priority or "",
            "search_query": q,
            "page": page,
            "pages": pages,
            "page_size": page_size,
            "previous_url": (
                str(request.url.include_query_params(page=page - 1)) if page > 1 else None
            ),
            "next_url": (
                str(request.url.include_query_params(page=page + 1)) if page < pages else None
            ),
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
def start_case(
    case_id: uuid.UUID, session: DatabaseSession, post: str | None = None
) -> RedirectResponse:
    try:
        ReviewService(session).start_case(case_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        return _case_redirect(case_id, post=post, error=str(error))
    return _case_redirect(case_id, post=post, message="Review started")


@router.post("/cases/{case_id}/cancel")
def cancel_case(
    case_id: uuid.UUID, session: DatabaseSession, post: str | None = None
) -> RedirectResponse:
    try:
        ReviewService(session).cancel_case(case_id)
    except (ResourceNotFoundError, DomainConflictError) as error:
        return _case_redirect(case_id, post=post, error=str(error))
    return _case_redirect(case_id, post=post, message="Review case cancelled")


@router.post("/cases/{case_id}/submit")
async def submit_review_scope(
    request: Request,
    case_id: uuid.UUID,
    session: DatabaseSession,
    settings: ApplicationSettings,
) -> RedirectResponse:
    post: str | None = None
    try:
        form = await _read_form(request)
        post = (form.get("post") or "").strip() or None
        comment = (form.get("comment") or "").strip()
        final_action = form.get("final_action")
        if final_action not in {"APPROVE_POST", "REJECT_POST"}:
            raise ValueError("Choose Final Approve Post or Final Reject Post")
        service = ReviewService(session)
        item_decisions: dict[uuid.UUID, ReviewDecisionCreate] = {}
        for name, value in form.items():
            if not name.startswith("item_"):
                continue
            item_id = uuid.UUID(name.removeprefix("item_"))
            item = service.get_item(item_id)
            if item.review_case_id != case_id:
                raise ValueError("Review item does not belong to this case")
            if value == ReviewDecisionType.REJECT.value:
                decision = ReviewDecisionType.REJECT
                corrected_value = None
            elif value in {"APPROVE", ReviewDecisionType.APPROVE_AS_IS.value}:
                corrected_value = item.candidate_value_snapshot
                corrected_value_type = item.candidate_value_type_snapshot
                form_value = form.get(f"value_{item_id}")
                if form_value is not None and corrected_value_type is not None:
                    corrected_value = _typed_form_value(corrected_value_type, form_value)
                decision = (
                    ReviewDecisionType.APPROVE_AS_IS
                    if corrected_value == item.candidate_value_snapshot
                    else ReviewDecisionType.CORRECT_AND_APPROVE
                )
            else:
                raise ValueError("Choose Approve or Reject for every review item")
            item_decisions[item_id] = ReviewDecisionCreate(
                decision=decision,
                reviewer_identifier=settings.review_web_reviewer_identifier,
                decision_note=comment,
                corrected_value_type=(
                    item.candidate_value_type_snapshot
                    if decision == ReviewDecisionType.CORRECT_AND_APPROVE
                    else None
                ),
                corrected_value=(
                    corrected_value
                    if decision == ReviewDecisionType.CORRECT_AND_APPROVE
                    else None
                ),
            )
        service.submit_review_scope(
            case_id,
            post_key=post,
            item_decisions=item_decisions,
            reviewer_identifier=settings.review_web_reviewer_identifier,
            decision_note=comment,
            approve=final_action == "APPROVE_POST",
        )
    except (ValueError, ValidationError, DomainConflictError) as error:
        message = str(error)
        if isinstance(error, ValidationError):
            message = "; ".join(item["msg"] for item in error.errors())
        return _case_redirect(case_id, post=post, error=message)
    outcome = "approved" if final_action == "APPROVE_POST" else "rejected"
    label = "Post" if post is not None else "Advertisement"
    return _case_redirect(case_id, post=post, message=f"{label} {outcome}")


@router.post("/cases/{case_id}/publish")
async def publish_reviewed_post(
    request: Request,
    case_id: uuid.UUID,
    session: DatabaseSession,
) -> RedirectResponse:
    post: str | None = None
    try:
        form = await _read_form(request)
        post = (form.get("post") or "").strip() or None
        if post is None:
            raise ValueError("A focused Post is required for publication")
        review_case = ReviewService(session).get_case(case_id)
        _, revision, _, _ = MasterPublisherService(session).publish_post(
            review_case.revision_confidence_assessment_id,
            post,
        )
        published_post = next(
            (item for item in revision.posts if item.post_key == post), None
        )
        if published_post is None:
            raise DomainConflictError("Published Master revision does not contain this Post")
    except (ValueError, ResourceNotFoundError, DomainConflictError) as error:
        return _case_redirect(case_id, post=post, error=str(error))
    return _case_redirect(case_id, post=post, message="Job published")


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
    post: str | None = None
    try:
        form = await _read_form(request)
        post = (form.get("post") or "").strip() or None
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
        return _case_redirect(case_id, post=post, error=message)
    return _case_redirect(case_id, post=post, message="Decision recorded")
