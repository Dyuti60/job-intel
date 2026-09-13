import math
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.candidates import CandidateValueType
from app.models.master import MasterField
from app.repositories.public_recruitments import (
    PublicFieldSource,
    PublicMasterRecord,
    PublicRecruitmentRepository,
)
from app.schemas.public_recruitments import (
    PublicApplicationStatus,
    PublicApplicationWindowRead,
    PublicAuthorityRead,
    PublicRecruitmentDetail,
    PublicRecruitmentFieldRead,
    PublicRecruitmentPage,
    PublicRecruitmentSort,
    PublicRecruitmentSummary,
    PublicSourceRead,
)
from app.services.exceptions import ResourceNotFoundError

_AUTHORITY_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_CANDIDATE_KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


@dataclass(frozen=True)
class PublicRecruitmentFilters:
    authority_code: str | None = None
    candidate_key: str | None = None
    query: str | None = None
    post_name: str | None = None
    department: str | None = None
    qualification: str | None = None
    application_status: PublicApplicationStatus | None = None
    application_start_from: date | None = None
    application_start_to: date | None = None
    application_end_from: date | None = None
    application_end_to: date | None = None
    minimum_vacancies: int | None = None
    maximum_vacancies: int | None = None


@dataclass(frozen=True)
class _DerivedRecord:
    record: PublicMasterRecord
    application: PublicApplicationWindowRead
    vacancies_total: int | None
    post_name: str | None
    department: str | None
    qualification: str | None


class PublicRecruitmentService:
    def __init__(self, session: Session) -> None:
        self.repository = PublicRecruitmentRepository(session)

    def list_recruitments(
        self,
        *,
        filters: PublicRecruitmentFilters,
        sort: PublicRecruitmentSort,
        page: int,
        page_size: int,
        as_of: date | None = None,
    ) -> PublicRecruitmentPage:
        evaluated_on = as_of or datetime.now(UTC).date()
        self._validate_filters(filters)
        authority_code = self._normalize_identifier(
            filters.authority_code, "authority_code", _AUTHORITY_CODE
        )
        candidate_key = self._normalize_identifier(
            filters.candidate_key, "candidate_key", _CANDIDATE_KEY
        )
        query = self._normalize_query(filters.query)
        records = self.repository.list_current_active(
            authority_code=authority_code,
            candidate_key=candidate_key,
            query=query,
        )
        derived = [self._derive(record, evaluated_on) for record in records]
        filtered = [item for item in derived if self._matches(item, filters)]
        ordered = sorted(filtered, key=lambda item: self._sort_key(item, sort))
        total = len(ordered)
        start = (page - 1) * page_size
        items = [self._summary(item) for item in ordered[start : start + page_size]]
        return PublicRecruitmentPage(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    def _validate_filters(filters: PublicRecruitmentFilters) -> None:
        for name, value in {
            "post name": filters.post_name,
            "department": filters.department,
            "qualification": filters.qualification,
        }.items():
            if value is not None and len(" ".join(value.split())) > 100:
                raise ValueError(f"{name} filter must contain at most 100 characters")
        if (
            filters.application_start_from is not None
            and filters.application_start_to is not None
            and filters.application_start_from > filters.application_start_to
        ):
            raise ValueError("application start-date range is invalid")
        if (
            filters.application_end_from is not None
            and filters.application_end_to is not None
            and filters.application_end_from > filters.application_end_to
        ):
            raise ValueError("application end-date range is invalid")
        if (
            filters.minimum_vacancies is not None
            and filters.maximum_vacancies is not None
            and filters.minimum_vacancies > filters.maximum_vacancies
        ):
            raise ValueError("vacancy range is invalid")

    def get_recruitment(
        self, public_id: uuid.UUID, *, as_of: date | None = None
    ) -> PublicRecruitmentDetail:
        record = self.repository.get_current_active(public_id)
        if record is None:
            raise ResourceNotFoundError("Public recruitment not found")
        derived = self._derive(record, as_of or datetime.now(UTC).date())
        visible_fields = self._visible_fields(record)
        sources = self.repository.field_sources(visible_fields)
        if len(sources) != len(visible_fields) or any(
            source.authority.id != record.authority.id for source in sources.values()
        ):
            raise ResourceNotFoundError("Public recruitment provenance is unavailable")
        public_fields = [
            PublicRecruitmentFieldRead(
                field_path=self._public_path(record, field),
                value_type=field.value_type,
                value=field.value,
                source=self._source(sources[field.source_candidate_field_id]),
            )
            for field in sorted(visible_fields, key=lambda item: self._public_path(record, item))
            if field.source_candidate_field_id in sources
        ]
        unique_sources = {
            (
                source.document.document_url,
                source.endpoint.name,
                source.endpoint.source_class.value,
            ): self._source(source)
            for source in sources.values()
        }
        return PublicRecruitmentDetail(
            **self._summary(derived).model_dump(),
            fields=public_fields,
            sources=[unique_sources[key] for key in sorted(unique_sources)],
        )

    @staticmethod
    def _normalize_identifier(value: str | None, name: str, pattern: re.Pattern[str]) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not pattern.fullmatch(normalized):
            raise ValueError(f"{name} must be a stable Assam recruitment identifier")
        return normalized

    @staticmethod
    def _normalize_query(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            return None
        if len(normalized) > 100:
            raise ValueError("query must contain at most 100 characters")
        return normalized

    def _derive(self, record: PublicMasterRecord, evaluated_on: date) -> _DerivedRecord:
        fields = {self._public_path(record, field): field for field in self._visible_fields(record)}
        start = self._date_value(fields.get("application.start_date"))
        end = self._date_value(fields.get("application.end_date"))
        return _DerivedRecord(
            record=record,
            application=PublicApplicationWindowRead(
                start_date=start,
                end_date=end,
                status=self._application_status(start, end, evaluated_on),
                evaluated_on=evaluated_on,
            ),
            vacancies_total=self._integer_value(fields.get("vacancies.total")),
            post_name=(
                record.post.name
                if record.post is not None
                else self._string_value(fields.get("post.name"))
            ),
            department=self._string_value(
                fields.get("department") if "department" in fields else fields.get("organisation")
            ),
            qualification=self._string_value(
                fields.get("qualification.minimum")
                if "qualification.minimum" in fields
                else fields.get("eligibility.qualification.summary")
            ),
        )

    @staticmethod
    def _visible_fields(record: PublicMasterRecord) -> list[MasterField]:
        if record.post is None:
            return list(record.revision.fields)
        shared = [
            field for field in record.revision.fields if not field.field_path.startswith("posts.")
        ]
        return shared + [fact.master_field for fact in record.post.facts]

    @staticmethod
    def _public_path(record: PublicMasterRecord, field: MasterField) -> str:
        if record.post is None:
            return field.field_path
        return field.field_path.removeprefix(f"posts.{record.post.post_key}.")

    @staticmethod
    def _date_value(field: MasterField | None) -> date | None:
        if field is None or field.value_type != CandidateValueType.DATE:
            return None
        try:
            return date.fromisoformat(field.value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer_value(field: MasterField | None) -> int | None:
        if (
            field is None
            or field.value_type != CandidateValueType.INTEGER
            or type(field.value) is not int
        ):
            return None
        return field.value

    @staticmethod
    def _string_value(field: MasterField | None) -> str | None:
        if field is None or field.value_type != CandidateValueType.STRING:
            return None
        return field.value if isinstance(field.value, str) else None

    @staticmethod
    def _application_status(
        start: date | None, end: date | None, evaluated_on: date
    ) -> PublicApplicationStatus:
        if start is not None and end is not None and start > end:
            return PublicApplicationStatus.UNKNOWN
        if start is None and end is None:
            return PublicApplicationStatus.UNKNOWN
        if start is not None and evaluated_on < start:
            return PublicApplicationStatus.UPCOMING
        if end is not None and evaluated_on > end:
            return PublicApplicationStatus.CLOSED
        return PublicApplicationStatus.OPEN

    @staticmethod
    def _matches(item: _DerivedRecord, filters: PublicRecruitmentFilters) -> bool:
        app = item.application
        return all(
            (
                filters.application_status is None or app.status == filters.application_status,
                filters.application_start_from is None
                or (
                    app.start_date is not None and app.start_date >= filters.application_start_from
                ),
                filters.application_start_to is None
                or (app.start_date is not None and app.start_date <= filters.application_start_to),
                filters.application_end_from is None
                or (app.end_date is not None and app.end_date >= filters.application_end_from),
                filters.application_end_to is None
                or (app.end_date is not None and app.end_date <= filters.application_end_to),
                filters.minimum_vacancies is None
                or (
                    item.vacancies_total is not None
                    and item.vacancies_total >= filters.minimum_vacancies
                ),
                filters.maximum_vacancies is None
                or (
                    item.vacancies_total is not None
                    and item.vacancies_total <= filters.maximum_vacancies
                ),
                PublicRecruitmentService._contains(item.post_name, filters.post_name),
                PublicRecruitmentService._contains(item.department, filters.department),
                PublicRecruitmentService._contains(item.qualification, filters.qualification),
            )
        )

    @staticmethod
    def _contains(actual: str | None, expected: str | None) -> bool:
        if expected is None or not " ".join(expected.split()):
            return True
        return actual is not None and " ".join(expected.split()).casefold() in actual.casefold()

    @staticmethod
    def _sort_key(item: _DerivedRecord, sort: PublicRecruitmentSort) -> tuple:
        master = item.record.master
        stable = str(item.record.post.public_id if item.record.post is not None else master.id)
        if sort == PublicRecruitmentSort.PUBLISHED_ASC:
            return (master.last_published_at, stable)
        if sort == PublicRecruitmentSort.APPLICATION_END_ASC:
            return (
                item.application.end_date is None,
                item.application.end_date or date.max,
                stable,
            )
        if sort == PublicRecruitmentSort.APPLICATION_END_DESC:
            ordinal = -(item.application.end_date.toordinal()) if item.application.end_date else 0
            return (item.application.end_date is None, ordinal, stable)
        if sort == PublicRecruitmentSort.DISPLAY_NAME_ASC:
            return (
                (
                    item.record.post.name if item.record.post is not None else master.display_name
                ).casefold(),
                master.candidate_key,
                stable,
            )
        if sort == PublicRecruitmentSort.VACANCIES_DESC:
            vacancies = -item.vacancies_total if item.vacancies_total is not None else 0
            return (item.vacancies_total is None, vacancies, stable)
        return (-master.last_published_at.timestamp(), stable)

    @staticmethod
    def _summary(item: _DerivedRecord) -> PublicRecruitmentSummary:
        post = item.record.post
        return PublicRecruitmentSummary(
            id=post.public_id if post is not None else item.record.master.id,
            candidate_key=item.record.master.candidate_key,
            display_name=post.name if post is not None else item.record.revision.display_name,
            advertisement_title=item.record.revision.display_name,
            post_key=post.post_key if post is not None else None,
            authority=PublicAuthorityRead(
                code=item.record.authority.code,
                name=item.record.authority.name,
                official_website_url=item.record.authority.official_website_url,
            ),
            current_revision_number=item.record.revision.revision_number,
            published_at=item.record.revision.published_at,
            last_verified_at=item.record.master.last_verified_at,
            application=item.application,
            vacancies_total=item.vacancies_total,
            post_name=item.post_name,
        )

    @staticmethod
    def _source(source: PublicFieldSource) -> PublicSourceRead:
        return PublicSourceRead(
            document_url=source.document.document_url,
            document_type=source.document.document_type,
            endpoint_name=source.endpoint.name,
            source_class=source.endpoint.source_class,
            authority_code=source.authority.code,
        )
