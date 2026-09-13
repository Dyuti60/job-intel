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


@router.get("", response_class=HTMLResponse, name="public_jobs")
def public_jobs(
    request: Request,
    session: DatabaseSession,
    authority: str | None = None,
    candidate_key: str | None = None,
    query: Annotated[str | None, Query(alias="q")] = None,
    application_status: PublicApplicationStatus | None = None,
    application_start_from: date | None = None,
    application_start_to: date | None = None,
    application_end_from: date | None = None,
    application_end_to: date | None = None,
    minimum_vacancies: Annotated[int | None, Query(ge=0)] = None,
    maximum_vacancies: Annotated[int | None, Query(ge=0)] = None,
    sort: PublicRecruitmentSort = PublicRecruitmentSort.PUBLISHED_DESC,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    as_of: date | None = None,
) -> HTMLResponse:
    try:
        result = PublicRecruitmentService(session).list_recruitments(
            filters=PublicRecruitmentFilters(
                authority_code=authority,
                candidate_key=candidate_key,
                query=query,
                application_status=application_status,
                application_start_from=application_start_from,
                application_start_to=application_start_to,
                application_end_from=application_end_from,
                application_end_to=application_end_to,
                minimum_vacancies=minimum_vacancies,
                maximum_vacancies=maximum_vacancies,
            ),
            sort=sort,
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
                "authority": authority or "",
                "candidate_key": candidate_key or "",
                "q": query or "",
                "application_status": application_status.value if application_status else "",
                "application_start_from": application_start_from or "",
                "application_start_to": application_start_to or "",
                "application_end_from": application_end_from or "",
                "application_end_to": application_end_to or "",
                "minimum_vacancies": minimum_vacancies if minimum_vacancies is not None else "",
                "maximum_vacancies": maximum_vacancies if maximum_vacancies is not None else "",
                "sort": sort.value,
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
