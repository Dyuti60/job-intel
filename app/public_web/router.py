import uuid
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.public_web.services import PublicRecruitmentViewService
from app.schemas.public_recruitments import PublicApplicationStatus, PublicRecruitmentSort
from app.services.exceptions import ResourceNotFoundError
from app.services.public_recruitments import PublicRecruitmentFilters, PublicRecruitmentService

router = APIRouter(prefix="/jobs", tags=["public-web"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
DatabaseSession = Annotated[Session, Depends(get_db)]


def _page_url(request: Request, page: int) -> str:
    return str(request.url.include_query_params(page=page))


def _optional_date(value: str | None, label: str) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as error:
        raise ValueError(f"{label} must be a valid date in YYYY-MM-DD format") from error


def _optional_nonnegative_int(value: str | None, label: str) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value.strip())
    except ValueError as error:
        raise ValueError(f"{label} must be a whole number") from error
    if parsed < 0:
        raise ValueError(f"{label} must be zero or greater")
    return parsed


@router.get("", response_class=HTMLResponse, name="public_jobs")
def public_jobs(
    request: Request,
    session: DatabaseSession,
    authority: str | None = None,
    candidate_key: str | None = None,
    query: Annotated[str | None, Query(alias="q")] = None,
    application_status: str | None = None,
    application_start_from: str | None = None,
    application_start_to: str | None = None,
    application_end_from: str | None = None,
    application_end_to: str | None = None,
    minimum_vacancies: str | None = None,
    maximum_vacancies: str | None = None,
    sort: str = PublicRecruitmentSort.PUBLISHED_DESC.value,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    as_of: date | None = None,
) -> HTMLResponse:
    try:
        parsed_authority = authority.strip() if authority and authority.strip() else None
        parsed_candidate_key = (
            candidate_key.strip() if candidate_key and candidate_key.strip() else None
        )
        parsed_query = query.strip() if query and query.strip() else None
        parsed_status = (
            PublicApplicationStatus(application_status.strip())
            if application_status and application_status.strip()
            else None
        )
        parsed_sort = PublicRecruitmentSort(
            sort.strip() or PublicRecruitmentSort.PUBLISHED_DESC.value
        )
        parsed_application_start_from = _optional_date(
            application_start_from, "Application start date"
        )
        parsed_application_start_to = _optional_date(
            application_start_to, "Application start date"
        )
        parsed_application_end_from = _optional_date(
            application_end_from, "Application closing date"
        )
        parsed_application_end_to = _optional_date(
            application_end_to, "Application closing date"
        )
        parsed_minimum_vacancies = _optional_nonnegative_int(
            minimum_vacancies, "Minimum vacancies"
        )
        parsed_maximum_vacancies = _optional_nonnegative_int(
            maximum_vacancies, "Maximum vacancies"
        )
        result = PublicRecruitmentService(session).list_recruitments(
            filters=PublicRecruitmentFilters(
                authority_code=parsed_authority,
                candidate_key=parsed_candidate_key,
                query=parsed_query,
                application_status=parsed_status,
                application_start_from=parsed_application_start_from,
                application_start_to=parsed_application_start_to,
                application_end_from=parsed_application_end_from,
                application_end_to=parsed_application_end_to,
                minimum_vacancies=parsed_minimum_vacancies,
                maximum_vacancies=parsed_maximum_vacancies,
            ),
            sort=parsed_sort,
            page=page,
            page_size=page_size,
            as_of=as_of,
        )
    except ValueError as error:
        return templates.TemplateResponse(
            request=request,
            name="public/error.html",
            context={"request": request, "title": "Invalid search", "message": str(error)},
            status_code=422,
        )
    return templates.TemplateResponse(
        request=request,
        name="public/jobs.html",
        context={
            "request": request,
            "title": "Assam Government Recruitments",
            "description": "Current approved Assam Government recruitment opportunities.",
            "canonical_url": str(request.url.replace(query="")),
            "result": result,
            "statuses": list(PublicApplicationStatus),
            "sort_options": list(PublicRecruitmentSort),
            "filters": {
                "authority": parsed_authority or "",
                "candidate_key": parsed_candidate_key or "",
                "q": parsed_query or "",
                "application_status": parsed_status.value if parsed_status else "",
                "application_start_from": parsed_application_start_from or "",
                "application_start_to": parsed_application_start_to or "",
                "application_end_from": parsed_application_end_from or "",
                "application_end_to": parsed_application_end_to or "",
                "minimum_vacancies": (
                    parsed_minimum_vacancies
                    if parsed_minimum_vacancies is not None
                    else ""
                ),
                "maximum_vacancies": (
                    parsed_maximum_vacancies
                    if parsed_maximum_vacancies is not None
                    else ""
                ),
                "sort": parsed_sort.value,
                "page_size": page_size,
                "as_of": as_of or "",
            },
            "previous_url": _page_url(request, page - 1) if page > 1 else None,
            "next_url": _page_url(request, page + 1) if page < result.pages else None,
        },
    )


@router.get("/{master_id}", response_class=HTMLResponse, name="public_job_detail")
def public_job_detail(
    master_id: uuid.UUID,
    request: Request,
    session: DatabaseSession,
    as_of: date | None = None,
) -> HTMLResponse:
    try:
        recruitment = PublicRecruitmentService(session).get_recruitment(master_id, as_of=as_of)
    except ResourceNotFoundError:
        return templates.TemplateResponse(
            request=request,
            name="public/error.html",
            context={
                "request": request,
                "title": "Recruitment not found",
                "message": "This approved recruitment is not available.",
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="public/job_detail.html",
        context={
            "request": request,
            "title": recruitment.display_name,
            "description": (
                f"Approved Assam Government recruitment information for "
                f"{recruitment.display_name}."
            ),
            "canonical_url": str(request.url.replace(query="")),
            "view": PublicRecruitmentViewService.detail(recruitment),
        },
    )
