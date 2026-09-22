import enum
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.candidates import CandidateValueType
from app.models.discovery import DocumentType
from app.models.source_registry import SourceClass
from app.services.job_lifecycle import JobLifecycle


class PublicSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicApplicationStatus(enum.StrEnum):
    UPCOMING = "UPCOMING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class PublicRecruitmentSort(enum.StrEnum):
    LIFECYCLE = "lifecycle"
    PUBLISHED_DESC = "published_desc"
    PUBLISHED_ASC = "published_asc"
    APPLICATION_END_ASC = "application_end_asc"
    APPLICATION_END_DESC = "application_end_desc"
    DISPLAY_NAME_ASC = "display_name_asc"
    VACANCIES_DESC = "vacancies_desc"


class PublicAuthorityRead(PublicSchema):
    code: str
    name: str
    official_website_url: str


class PublicSourceRead(PublicSchema):
    document_url: str
    document_type: DocumentType
    label: str
    endpoint_name: str
    source_class: SourceClass
    authority_code: str


class PublicApplicationWindowRead(PublicSchema):
    start_date: date | None
    end_date: date | None
    status: PublicApplicationStatus
    evaluated_on: date


class PublicRecruitmentSummary(PublicSchema):
    id: uuid.UUID
    advertisement_id: uuid.UUID
    candidate_key: str
    display_name: str
    advertisement_title: str
    post_key: str | None
    authority: PublicAuthorityRead
    current_revision_number: int
    published_at: datetime
    last_verified_at: datetime
    application: PublicApplicationWindowRead
    lifecycle: JobLifecycle
    vacancies_total: int | None
    post_name: str | None
    organisation: str | None
    qualification_summary: str | None


class PublicRecruitmentFieldRead(PublicSchema):
    field_path: str
    value_type: CandidateValueType
    value: Any
    source: PublicSourceRead


class PublicRecruitmentDetail(PublicRecruitmentSummary):
    fields: list[PublicRecruitmentFieldRead]
    sources: list[PublicSourceRead]


class PublicAdvertisementSummary(PublicSchema):
    id: uuid.UUID
    title: str
    authority: PublicAuthorityRead
    current_revision_number: int
    fields: list[PublicRecruitmentFieldRead]
    posts: list[PublicRecruitmentSummary]
    sources: list[PublicSourceRead]


class PublicRecruitmentPage(PublicSchema):
    items: list[PublicRecruitmentSummary]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)
