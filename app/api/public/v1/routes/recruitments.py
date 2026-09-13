import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.public_recruitments import (
    PublicApplicationStatus,
    PublicRecruitmentDetail,
    PublicRecruitmentPage,
    PublicRecruitmentSort,
)
from app.services.exceptions import ResourceNotFoundError
from app.services.public_recruitments import (
    PublicRecruitmentFilters,
    PublicRecruitmentService,
)

router = APIRouter(prefix="/recruitments", tags=["public-recruitments"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=PublicRecruitmentPage)
def list_public_recruitments(
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
) -> PublicRecruitmentPage:
    if (
        application_start_from is not None
        and application_start_to is not None
        and application_start_from > application_start_to
    ):
        raise HTTPException(status_code=422, detail="application start-date range is invalid")
    if (
        application_end_from is not None
        and application_end_to is not None
        and application_end_from > application_end_to
    ):
        raise HTTPException(status_code=422, detail="application end-date range is invalid")
    if (
        minimum_vacancies is not None
        and maximum_vacancies is not None
        and minimum_vacancies > maximum_vacancies
    ):
        raise HTTPException(status_code=422, detail="vacancy range is invalid")
    try:
        return PublicRecruitmentService(session).list_recruitments(
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
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/{master_id}", response_model=PublicRecruitmentDetail)
def get_public_recruitment(
    master_id: uuid.UUID,
    session: DatabaseSession,
    as_of: date | None = None,
) -> PublicRecruitmentDetail:
    try:
        return PublicRecruitmentService(session).get_recruitment(master_id, as_of=as_of)
    except ResourceNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
