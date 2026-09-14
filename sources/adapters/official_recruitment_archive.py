import hashlib
import io
import re
from dataclasses import dataclass, replace
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin

from pypdf import PdfReader

from app.models.candidates import AdvertisementSplitStatus, CandidateValueType
from app.models.discovery import DocumentType
from app.models.source_registry import AuthorityType, SourceScheduleGroup
from sources.adapters.apsc_recruitment import AdapterDocument
from sources.extraction import ParsedAdvertisement, ParsedField, ParsedPost
from sources.http import BoundedHttpClient


@dataclass(frozen=True)
class OfficialArchiveSource:
    source_code: str
    authority_code: str
    authority_name: str
    authority_type: AuthorityType
    listing_url: str
    adapter_key: str
    organization_name: str
    schedule_group: SourceScheduleGroup = SourceScheduleGroup.NORMAL
    poll_interval_minutes: int = 1440
    priority: int = 100
    requests_per_minute: int = 6
    accepts_download_links: bool = False
    max_notices_per_run: int = 50


OFFICIAL_ARCHIVE_SOURCES = {
    "SLPRB_ASSAM": OfficialArchiveSource(
        source_code="SLPRB_ASSAM",
        authority_code="SLPRB_ASSAM",
        authority_name="State Level Police Recruitment Board, Assam",
        authority_type=AuthorityType.POLICE,
        listing_url="https://slprbassam.in/",
        adapter_key="official_archive_slprb",
        organization_name="State Level Police Recruitment Board, Assam",
        schedule_group=SourceScheduleGroup.HIGH_PRIORITY,
        poll_interval_minutes=360,
        priority=20,
    ),
    "DEE_ASSAM": OfficialArchiveSource(
        source_code="DEE_ASSAM",
        authority_code="DEE_ASSAM",
        authority_name="Directorate of Elementary Education, Assam",
        authority_type=AuthorityType.DEPARTMENT,
        listing_url="https://dee.assam.gov.in/portlets/recruitment-under-dee-assam",
        adapter_key="official_archive_dee",
        organization_name="Directorate of Elementary Education, Assam",
        schedule_group=SourceScheduleGroup.HIGH_PRIORITY,
        poll_interval_minutes=720,
        priority=30,
    ),
    "DME_ASSAM": OfficialArchiveSource(
        source_code="DME_ASSAM",
        authority_code="DME_ASSAM",
        authority_name="Directorate of Medical Education, Assam",
        authority_type=AuthorityType.DEPARTMENT,
        listing_url="https://dme.assam.gov.in/documents-detail/recruitment",
        adapter_key="official_archive_dme",
        organization_name="Directorate of Medical Education, Assam",
        priority=40,
    ),
    "ASDMA_ASSAM": OfficialArchiveSource(
        source_code="ASDMA_ASSAM",
        authority_code="ASDMA_ASSAM",
        authority_name="Assam State Disaster Management Authority",
        authority_type=AuthorityType.AUTONOMOUS_BODY,
        listing_url="https://asdma.assam.gov.in/resource/recruitment",
        adapter_key="structured_resource_table_asdma",
        organization_name="Assam State Disaster Management Authority",
        priority=60,
        requests_per_minute=4,
        accepts_download_links=True,
    ),
}


@dataclass(frozen=True)
class ArchiveNoticeMetadata:
    title: str
    document_url: str
    notification_number: str | None
    notification_date: date | None


@dataclass(frozen=True)
class ArchiveNotice:
    metadata: ArchiveNoticeMetadata
    document: AdapterDocument
    candidate_key: str
    fields: tuple[ParsedField, ...]
    posts: tuple[ParsedPost, ...] = ()
    split_status: AdvertisementSplitStatus = AdvertisementSplitStatus.LEGACY_UNSPLIT
    split_note: str | None = None


@dataclass(frozen=True)
class ArchiveAdapterResult:
    listing_document: AdapterDocument
    notices: tuple[ArchiveNotice, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _Link:
    url: str
    text: str


@dataclass(frozen=True)
class _Row:
    cells: tuple[str, ...]
    links: tuple[_Link, ...]


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[_Row] = []
        self._in_row = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._cells: list[str] = []
        self._links: list[_Link] = []
        self._link_url: str | None = None
        self._link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self._in_row = True
            self._cells = []
            self._links = []
        elif tag == "td" and self._in_row:
            self._in_cell = True
            self._cell_parts = []
        elif tag == "a" and self._in_row:
            self._link_url = attributes.get("href")
            self._link_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)
        if self._link_url is not None:
            self._link_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_url is not None:
            self._links.append(_Link(self._link_url, _clean_text(" ".join(self._link_parts))))
            self._link_url = None
            self._link_parts = []
        elif tag == "td" and self._in_cell:
            self._cells.append(_clean_text(" ".join(self._cell_parts)))
            self._in_cell = False
            self._cell_parts = []
        elif tag == "tr" and self._in_row:
            if self._cells:
                self.rows.append(_Row(tuple(self._cells), tuple(self._links)))
            self._in_row = False


class OfficialRecruitmentArchiveAdapter:
    """Discover dated recruitment advertisements from one registered official archive."""

    def __init__(
        self,
        http: BoundedHttpClient,
        source: OfficialArchiveSource,
        *,
        earliest_year: int,
    ) -> None:
        self.http = http
        self.source = source
        self.earliest_year = earliest_year

    def discover(self) -> ArchiveAdapterResult:
        listing = self.http.fetch(self.source.listing_url, accepted_types=("text/html",))
        metadata = parse_archive_listing(
            listing.content,
            self.source,
            earliest_year=self.earliest_year,
        )
        notices: list[ArchiveNotice] = []
        warnings: list[str] = []
        if len(metadata) > self.source.max_notices_per_run:
            warnings.append(
                f"Listing returned {len(metadata)} advertisements; processed bounded first "
                f"{self.source.max_notices_per_run} in deterministic URL order"
            )
        for item in metadata[: self.source.max_notices_per_run]:
            try:
                resource = self.http.fetch(item.document_url, accepted_types=("application/pdf",))
                extraction = parse_official_advertisement_pdf(
                    resource.content,
                    item,
                    self.source.organization_name,
                )
                if not extraction.fields and not extraction.posts:
                    warnings.append(f"No supported fields extracted from {item.document_url}")
                warnings.extend(extraction.warnings)
                notices.append(
                    ArchiveNotice(
                        metadata=item,
                        document=AdapterDocument(resource, DocumentType.PDF, "pdf"),
                        candidate_key=archive_candidate_key(self.source.authority_code, item),
                        fields=extraction.fields,
                        posts=extraction.posts,
                        split_status=extraction.split_status,
                        split_note=extraction.split_note,
                    )
                )
            except Exception as error:
                warnings.append(
                    f"Advertisement unavailable {item.document_url}: "
                    f"{type(error).__name__}: {error}"
                )
        return ArchiveAdapterResult(
            listing_document=AdapterDocument(listing, DocumentType.HTML, "html"),
            notices=tuple(notices),
            warnings=tuple(warnings),
        )


def parse_archive_listing(
    content: bytes,
    source: OfficialArchiveSource,
    *,
    earliest_year: int,
) -> list[ArchiveNoticeMetadata]:
    parser = _TableParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    selected: dict[str, ArchiveNoticeMetadata] = {}
    for row in parser.rows:
        item = _metadata_from_row(row, source)
        if item is None:
            continue
        year = item.notification_date.year if item.notification_date else _explicit_year(item.title)
        if year is None or year < earliest_year:
            continue
        selected[item.document_url] = item
    return [selected[url] for url in sorted(selected)]


def _metadata_from_row(
    row: _Row, source: OfficialArchiveSource
) -> ArchiveNoticeMetadata | None:
    pdf_links = [
        link
        for link in row.links
        if ".pdf" in link.url.casefold()
        or (source.accepts_download_links and link.text.casefold() == "download")
    ]
    if not pdf_links:
        return None
    if source.source_code == "SLPRB_ASSAM":
        advertisement_links = [
            link
            for link in pdf_links
            if link.text.casefold() == "advertisement"
            or re.search(r"(?:^|[/_-])adv(?:ertisement)?[_-]", link.url, re.I)
        ]
        if not advertisement_links or len(row.cells) < 3:
            return None
        parsed_date = _parse_numeric_date(row.cells[0])
        if parsed_date is None:
            return None
        title = re.sub(r"\s+Advertisement\s*$", "", row.cells[2], flags=re.I).strip()
        reference = re.sub(r"\s+", " ", row.cells[1]).strip() or None
        link = advertisement_links[0]
        return ArchiveNoticeMetadata(
            title=title,
            document_url=urljoin(source.listing_url, link.url),
            notification_number=reference,
            notification_date=parsed_date,
        )

    title_link = next(
        (link for link in pdf_links if link.text and link.text.casefold() != "download"),
        pdf_links[0],
    )
    title = title_link.text
    if not title or title.casefold() == "download":
        title = next(
            (
                cell
                for cell in row.cells
                if cell and cell.casefold() != "download" and _parse_numeric_date(cell) is None
            ),
            "",
        )
    title = _clean_text(title)
    if not title:
        return None
    lowered = title.casefold()
    is_advertisement = any(
        word in lowered for word in ("advertisement", "recruitment", "vacancy")
    )
    excluded = any(
        word in lowered
        for word in (
            "result",
            "merit list",
            "select list",
            "shortlist",
            "verification",
            "interview",
            "admit card",
            "withdrawal",
            "cancellation",
            "cancelled",
            "appointment",
            "answer key",
            "postponement",
            "extension",
            "corrigendum",
            "addendum",
        )
    )
    if not is_advertisement or excluded:
        return None
    return ArchiveNoticeMetadata(
        title=title,
        document_url=urljoin(source.listing_url, title_link.url),
        notification_number=None,
        notification_date=_date_from_title(title)
        or next(
            (_parse_numeric_date(cell) for cell in row.cells if _parse_numeric_date(cell)),
            None,
        ),
    )


def parse_official_advertisement_pdf(
    content: bytes,
    metadata: ArchiveNoticeMetadata,
    organization_name: str,
) -> ParsedAdvertisement:
    reader = PdfReader(io.BytesIO(content))
    text_parts: list[str] = []
    size = 0
    for page in reader.pages[:30]:
        page_text = page.extract_text() or ""
        remaining = 120_000 - size
        if remaining <= 0:
            break
        text_parts.append(page_text[:remaining])
        size += len(page_text[:remaining])
    return parse_official_advertisement_text(
        "\n".join(text_parts), metadata, organization_name
    )


def parse_official_advertisement_text(
    raw_text: str,
    metadata: ArchiveNoticeMetadata,
    organization_name: str,
) -> ParsedAdvertisement:
    text = _clean_text(raw_text)
    if not text:
        return ParsedAdvertisement(fields=())
    excerpt = text[:8000]
    locator = "pdf:pages=1-30"
    fields = [
        ParsedField(
            "recruitment_name",
            CandidateValueType.STRING,
            metadata.title,
            metadata.title,
            locator,
            excerpt,
        ),
        ParsedField(
            "organization.name",
            CandidateValueType.STRING,
            organization_name,
            organization_name,
            locator,
            excerpt,
        ),
    ]
    reference = metadata.notification_number or _notification_number(text)
    if reference:
        fields.append(
            ParsedField(
                "notification.number",
                CandidateValueType.STRING,
                reference,
                reference,
                locator,
                excerpt,
            )
        )
    notification_date = metadata.notification_date or _document_date(text)
    if notification_date:
        raw_date = notification_date.strftime("%d/%m/%Y")
        fields.append(
            ParsedField(
                "notification.date",
                CandidateValueType.DATE,
                notification_date.isoformat(),
                raw_date,
                locator,
                excerpt,
            )
        )
    vacancy_total = _vacancy_total(metadata.title, text)
    if vacancy_total is not None:
        fields.append(
            ParsedField(
                "vacancies.total",
                CandidateValueType.INTEGER,
                vacancy_total,
                str(vacancy_total),
                locator,
                excerpt,
            )
        )
    dates = _application_dates(text)
    for path, value in dates.items():
        fields.append(
            ParsedField(
                path,
                CandidateValueType.DATE,
                value.isoformat(),
                value.strftime("%d/%m/%Y"),
                locator,
                excerpt,
            )
        )
    if re.search(r"online applications?", text, re.I):
        fields.append(
            ParsedField(
                "application.mode",
                CandidateValueType.STRING,
                "ONLINE",
                "online",
                locator,
                excerpt,
            )
        )
    unique = {field.field_path: field for field in fields}
    posts, split_status, split_note, warnings = parse_vacancy_table(raw_text)
    if split_status == AdvertisementSplitStatus.LEGACY_UNSPLIT:
        posts, split_status, split_note, warnings = parse_narrative_vacancies(
            metadata.title, raw_text
        )
    if split_status == AdvertisementSplitStatus.EXPLICIT:
        posts, ambiguities = apply_post_detail_tables(raw_text, posts)
        if ambiguities:
            warnings = (*warnings, *ambiguities)
            ambiguity_excerpt = "; ".join(ambiguities)[:8000]
            unique["extraction.ambiguities"] = ParsedField(
                "extraction.ambiguities",
                CandidateValueType.JSON,
                list(ambiguities),
                ambiguity_excerpt,
                "pdf:post-detail-tables",
                ambiguity_excerpt,
            )
    return ParsedAdvertisement(
        fields=tuple(unique[path] for path in sorted(unique)),
        posts=posts,
        split_status=split_status,
        split_note=split_note,
        warnings=warnings,
    )


_VACANCY_HEADERS = {
    "post": "post_name",
    "postname": "post_name",
    "nameofpost": "post_name",
    "nameofthepost": "post_name",
    "department": "department",
    "dept": "department",
    "organisation": "organisation",
    "organization": "organisation",
    "unitorganisation": "organisation",
    "unitorganization": "organisation",
    "ur": "vacancies.ur",
    "unreserved": "vacancies.ur",
    "obcmobc": "vacancies.obc_mobc",
    "obc": "vacancies.obc_mobc",
    "sc": "vacancies.sc",
    "stp": "vacancies.st_p",
    "sth": "vacancies.st_h",
    "ews": "vacancies.ews",
    "pwbd": "vacancies.pwbd",
    "pwd": "vacancies.pwbd",
    "women": "vacancies.women",
    "total": "vacancies.total",
    "totalposts": "vacancies.total",
    "noofposts": "vacancies.total",
    "numberofposts": "vacancies.total",
}

_POST_DETAIL_HEADERS = {
    "post": "post_name",
    "postname": "post_name",
    "nameofpost": "post_name",
    "nameofthepost": "post_name",
    "organisation": "organisation",
    "organization": "organisation",
    "department": "department",
    "minimumqualification": "qualification.minimum",
    "essentialqualification": "qualification.minimum",
    "qualification": "qualification.minimum",
    "desirablequalification": "qualification.desirable",
    "subject": "qualification.subject",
    "specialisation": "qualification.specialisation",
    "specialization": "qualification.specialisation",
    "minimumage": "age.minimum",
    "maximumage": "age.maximum",
    "payscale": "pay.scale",
    "gradepay": "pay.grade_pay",
    "minimumexperience": "experience.minimum",
    "desirableexperience": "experience.desirable",
}

_INTEGER_POST_FACTS = {"age.minimum", "age.maximum"}


def parse_vacancy_table(
    raw_text: str,
) -> tuple[
    tuple[ParsedPost, ...],
    AdvertisementSplitStatus,
    str | None,
    tuple[str, ...],
]:
    """Parse a bounded pipe-delimited vacancy table or retain explicit ambiguity."""
    lines = [line.strip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    candidates: list[tuple[int, list[str], dict[int, str]]] = []
    for index, line in enumerate(lines):
        if "|" not in line:
            continue
        cells = _table_cells(line)
        mapped = {
            cell_index: _VACANCY_HEADERS[key]
            for cell_index, cell in enumerate(cells)
            if (key := _header_key(cell)) in _VACANCY_HEADERS
        }
        if "post_name" in mapped.values() and "vacancies.total" in mapped.values():
            candidates.append((index, cells, mapped))
    if not candidates:
        return (), AdvertisementSplitStatus.LEGACY_UNSPLIT, None, ()
    if len(candidates) != 1:
        note = "Multiple vacancy tables matched; post ownership requires Human Review."
        return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)

    header_index, headers, mapped = candidates[0]
    rows: list[list[str]] = []
    for line in lines[header_index + 1 : header_index + 102]:
        if not line:
            if rows:
                break
            continue
        if "|" not in line:
            if rows:
                break
            continue
        cells = _table_cells(line)
        if _separator_row(cells):
            continue
        rows.append(cells)
    if not rows:
        note = "Vacancy table header was found but no deterministic post rows followed."
        return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)

    parsed: list[ParsedPost] = []
    seen_keys: set[str] = set()
    errors: list[str] = []
    for row_number, cells in enumerate(rows, start=1):
        if len(cells) != len(headers):
            errors.append(
                f"Vacancy row {row_number} has {len(cells)} cells; expected {len(headers)}"
            )
            continue
        values = {meaning: cells[column] for column, meaning in mapped.items()}
        name = _clean_text(values.get("post_name", ""))
        total_text = values.get("vacancies.total", "")
        if not name or not re.fullmatch(r"\d+", total_text.strip()):
            errors.append(f"Vacancy row {row_number} has an unsupported post name or total")
            continue
        primary_categories = (
            "vacancies.ur",
            "vacancies.obc_mobc",
            "vacancies.sc",
            "vacancies.st_p",
            "vacancies.st_h",
            "vacancies.ews",
        )
        if all(key in values for key in primary_categories) and all(
            re.fullmatch(r"\d+", values[key].strip()) for key in primary_categories
        ):
            category_total = sum(int(values[key]) for key in primary_categories)
            if category_total != int(total_text):
                errors.append(
                    f"Vacancy row {row_number} category total {category_total} "
                    f"does not match stated total {total_text}"
                )
                continue
        organisation = _clean_text(values.get("organisation", ""))
        department = _clean_text(values.get("department", ""))
        post_key = _stable_post_key(name, organisation or department)
        if post_key in seen_keys:
            errors.append(f"Vacancy row {row_number} duplicates stable post key {post_key}")
            continue
        seen_keys.add(post_key)
        row_excerpt = " | ".join(cells)[:8000]
        row_locator = f"pdf:table=vacancies;row={row_number}"
        facts = [
            ParsedField(
                "name",
                CandidateValueType.STRING,
                name,
                values["post_name"],
                f"{row_locator};column=post",
                row_excerpt,
            ),
            ParsedField(
                "vacancies.total",
                CandidateValueType.INTEGER,
                int(total_text),
                total_text,
                f"{row_locator};column=total",
                row_excerpt,
            ),
        ]
        for fact_key, value in sorted(values.items()):
            if fact_key in {"post_name", "vacancies.total"}:
                continue
            if fact_key == "organisation" and value.strip():
                facts.append(
                    ParsedField(
                        "organisation.name",
                        CandidateValueType.STRING,
                        _clean_text(value),
                        value,
                        f"{row_locator};column=organisation",
                        row_excerpt,
                    )
                )
            elif fact_key == "department" and value.strip():
                facts.append(
                    ParsedField(
                        "department.name",
                        CandidateValueType.STRING,
                        _clean_text(value),
                        value,
                        f"{row_locator};column=department",
                        row_excerpt,
                    )
                )
            elif fact_key.startswith("vacancies.") and re.fullmatch(r"\d+", value.strip()):
                facts.append(
                    ParsedField(
                        fact_key,
                        CandidateValueType.INTEGER,
                        int(value),
                        value,
                        f"{row_locator};column={fact_key.removeprefix('vacancies.')}",
                        row_excerpt,
                    )
                )
        parsed.append(
            ParsedPost(
                post_key=post_key,
                ordinal=row_number,
                name=name,
                normalized_name=" ".join(name.casefold().split()),
                source_locator=row_locator,
                facts=tuple(sorted(facts, key=lambda fact: fact.field_path)),
            )
        )
    if errors or len(parsed) != len(rows):
        note = "; ".join(errors)[:4000] or "Vacancy table could not be split safely."
        return (), AdvertisementSplitStatus.AMBIGUOUS, note, tuple(errors or [note])
    return (
        _qualify_duplicate_post_names(tuple(parsed)),
        AdvertisementSplitStatus.EXPLICIT,
        f"Deterministically parsed {len(parsed)} post rows from the vacancy table.",
        (),
    )


_NARRATIVE_POST = re.compile(
    r"\b(?P<total>[0-9][0-9,]*)\s+posts?\s+of\s+"
    r"(?P<name>.+?)\s+(?:in|under)\s+(?P<organisation>.+?)"
    r"(?=(?:,\s*|\s+and\s+)[0-9][0-9,]*\s+posts?\s+of\b|[.;]|$)",
    re.I,
)


def parse_narrative_vacancies(
    title: str, raw_text: str
) -> tuple[
    tuple[ParsedPost, ...],
    AdvertisementSplitStatus,
    str | None,
    tuple[str, ...],
]:
    """Split an explicit bounded ``N posts of X in/under Y`` series."""
    matches: list[re.Match[str]] = []
    markers = 0
    for candidate in (_clean_text(title), _clean_text(raw_text[:8000])):
        candidate_markers = len(
            re.findall(r"\b[0-9][0-9,]*\s+posts?\s+of\b", candidate, re.I)
        )
        candidate_matches = list(_NARRATIVE_POST.finditer(candidate))
        if len(candidate_matches) >= 2 or candidate_markers >= 2:
            matches = candidate_matches
            markers = candidate_markers
            break
    if len(matches) < 2:
        if markers >= 2:
            note = "Narrative vacancy series could not be split completely and safely."
            return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)
        return (), AdvertisementSplitStatus.LEGACY_UNSPLIT, None, ()
    if len(matches) != markers:
        note = "Narrative vacancy series was only partially matched; no Posts were created."
        return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)

    parsed: list[ParsedPost] = []
    seen_keys: set[str] = set()
    for ordinal, match in enumerate(matches, start=1):
        name = _clean_text(match.group("name")).strip(" ,-:")
        organisation = _clean_text(match.group("organisation")).strip(" ,-:")
        if not name or not organisation:
            note = "Narrative vacancy series contains an incomplete Post or organization."
            return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)
        total = int(match.group("total").replace(",", ""))
        post_key = _stable_post_key(name, organisation)
        if total < 1 or post_key in seen_keys:
            note = "Narrative vacancy series contains an invalid total or duplicate Post."
            return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)
        seen_keys.add(post_key)
        locator = f"pdf:narrative-vacancies;item={ordinal}"
        excerpt = match.group(0)[:8000]
        parsed.append(
            ParsedPost(
                post_key=post_key,
                ordinal=ordinal,
                name=name,
                normalized_name=" ".join(name.casefold().split()),
                source_locator=locator,
                facts=(
                    ParsedField(
                        "name",
                        CandidateValueType.STRING,
                        name,
                        match.group("name"),
                        f"{locator};field=post",
                        excerpt,
                    ),
                    ParsedField(
                        "organisation.name",
                        CandidateValueType.STRING,
                        organisation,
                        match.group("organisation"),
                        f"{locator};field=organisation",
                        excerpt,
                    ),
                    ParsedField(
                        "vacancies.total",
                        CandidateValueType.INTEGER,
                        total,
                        match.group("total"),
                        f"{locator};field=total",
                        excerpt,
                    ),
                ),
            )
        )
    posts = _qualify_duplicate_post_names(tuple(parsed))
    return (
        posts,
        AdvertisementSplitStatus.EXPLICIT,
        f"Deterministically parsed {len(posts)} Posts from an explicit vacancy series.",
        (),
    )


def _qualify_duplicate_post_names(posts: tuple[ParsedPost, ...]) -> tuple[ParsedPost, ...]:
    counts: dict[str, int] = {}
    for post in posts:
        counts[post.normalized_name] = counts.get(post.normalized_name, 0) + 1
    qualified: list[ParsedPost] = []
    for post in posts:
        if counts[post.normalized_name] == 1:
            qualified.append(post)
            continue
        organisation = next(
            (
                str(fact.value)
                for fact in post.facts
                if fact.field_path in {"organisation.name", "department.name"}
            ),
            "",
        )
        if not organisation:
            qualified.append(post)
            continue
        base_name = " ".join(
            word.capitalize() if word.islower() else word for word in post.name.split()
        )
        display_name = f"{base_name} - {organisation}"
        facts = tuple(
            replace(fact, value=display_name)
            if fact.field_path == "name"
            else fact
            for fact in post.facts
        )
        qualified.append(replace(post, name=display_name, facts=facts))
    return tuple(qualified)


def apply_post_detail_tables(
    raw_text: str, posts: tuple[ParsedPost, ...]
) -> tuple[tuple[ParsedPost, ...], tuple[str, ...]]:
    """Attach deterministic post-wise detail rows; report uncertain ownership as facts."""
    lines = [line.strip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    fact_maps = [{fact.field_path: fact for fact in post.facts} for post in posts]
    ambiguities: list[str] = []
    for header_index, line in enumerate(lines):
        if "|" not in line:
            continue
        headers = _table_cells(line)
        mapped = {
            column: _POST_DETAIL_HEADERS[key]
            for column, cell in enumerate(headers)
            if (key := _header_key(cell)) in _POST_DETAIL_HEADERS
        }
        detail_meanings = {
            meaning
            for meaning in mapped.values()
            if meaning not in {"post_name", "organisation", "department"}
        }
        if "post_name" not in mapped.values() or not detail_meanings:
            continue
        rows = _rows_after_header(lines, header_index, len(headers))
        for row_number, cells in enumerate(rows, start=1):
            locator = f"pdf:table=post-details-{header_index + 1};row={row_number}"
            if len(cells) != len(headers):
                ambiguities.append(f"Post detail row at {locator} has a damaged column shape")
                continue
            values = {meaning: cells[column] for column, meaning in mapped.items()}
            matches = _matching_post_indexes(posts, values)
            if len(matches) != 1:
                ambiguities.append(
                    f"Post detail row at {locator} matches {len(matches)} vacancy posts"
                )
                continue
            post_index = matches[0]
            excerpt = " | ".join(cells)[:8000]
            for fact_key in sorted(detail_meanings):
                raw_value = values.get(fact_key, "").strip()
                if not raw_value or raw_value in {"-", "—"}:
                    continue
                if fact_key in _INTEGER_POST_FACTS:
                    match = re.fullmatch(r"(\d{1,3})(?:\s*years?)?", raw_value, re.I)
                    if not match:
                        ambiguities.append(
                            f"Post detail {fact_key} at {locator} is not an exact integer age"
                        )
                        continue
                    value_type = CandidateValueType.INTEGER
                    value: object = int(match.group(1))
                else:
                    value_type = CandidateValueType.STRING
                    value = _clean_text(raw_value)
                parsed = ParsedField(
                    fact_key,
                    value_type,
                    value,
                    raw_value,
                    f"{locator};column={fact_key}",
                    excerpt,
                )
                existing = fact_maps[post_index].get(fact_key)
                if existing is not None and (
                    existing.value_type != parsed.value_type or existing.value != parsed.value
                ):
                    ambiguities.append(
                        f"Post detail {fact_key} at {locator} conflicts with another row"
                    )
                    continue
                fact_maps[post_index][fact_key] = parsed
    updated = tuple(
        replace(post, facts=tuple(facts[key] for key in sorted(facts)))
        for post, facts in zip(posts, fact_maps, strict=True)
    )
    return updated, tuple(ambiguities)


def _rows_after_header(lines: list[str], header_index: int, width: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines[header_index + 1 : header_index + 102]:
        if not line:
            if rows:
                break
            continue
        if "|" not in line:
            if rows:
                break
            continue
        cells = _table_cells(line)
        if _separator_row(cells):
            continue
        rows.append(cells)
        if len(rows) >= 100 or (rows and len(cells) != width):
            break
    return rows


def _matching_post_indexes(posts: tuple[ParsedPost, ...], values: dict[str, str]) -> list[int]:
    name = " ".join(_clean_text(values.get("post_name", "")).casefold().split())
    qualifier = _clean_text(values.get("organisation") or values.get("department") or "")
    matches = [index for index, post in enumerate(posts) if post.normalized_name == name]
    if qualifier:
        normalized_qualifier = " ".join(qualifier.casefold().split())
        matches = [
            index
            for index in matches
            if any(
                fact.field_path in {"organisation.name", "department.name"}
                and " ".join(str(fact.value).casefold().split()) == normalized_qualifier
                for fact in posts[index].facts
            )
        ]
    return matches


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r"[-: ]+", cell) for cell in cells)


def _stable_post_key(name: str, qualifier: str) -> str:
    seed = _clean_text(f"{name} {qualifier}").casefold()
    slug = re.sub(r"[^a-z0-9]+", "_", seed).strip("_")
    if not slug:
        slug = "post"
    if len(slug) > 110:
        slug = f"{slug[:97].rstrip('_')}_{hashlib.sha256(seed.encode()).hexdigest()[:12]}"
    return slug


def archive_candidate_key(authority_code: str, metadata: ArchiveNoticeMetadata) -> str:
    digest = hashlib.sha256(metadata.document_url.encode("utf-8")).hexdigest()[:12].upper()
    year = metadata.notification_date.year if metadata.notification_date else _explicit_year(
        metadata.title
    )
    return f"{authority_code}_ADVT_{year or 'UNKNOWN'}_{digest}"


def _notification_number(text: str) -> str | None:
    match = re.search(
        r"\b(?:No\.?|Advertisement\s+No\.?)\s*[:.-]?\s*"
        r"([A-Z][A-Z0-9 ()&./_-]{3,100}?)(?=\s+(?:Dated|Date)\b)",
        text,
        re.I,
    )
    return _clean_text(match.group(1)) if match else None


def _document_date(text: str) -> date | None:
    match = re.search(r"\b(?:Dated|Date)\s*[:.-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{4})", text, re.I)
    return _parse_numeric_date(match.group(1)) if match else None


def _application_dates(text: str) -> dict[str, date]:
    patterns = (
        r"(?:online applications?|application portal).{0,180}?"
        r"(?:from|opens?\s+on)\s*(\d{1,2}[./-]\d{1,2}[./-]\d{4})"
        r".{0,180}?(?:to|until|closes?\s+on)\s*(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
        r"(?:STARTING DATE|APPLICATION START DATE).{0,80}?(\d{1,2}[./-]\d{1,2}[./-]\d{4})"
        r".{0,400}?(?:CLOSING DATE|APPLICATION END DATE|LAST DATE)"
        r".{0,80}?(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            start = _parse_numeric_date(match.group(1))
            end = _parse_numeric_date(match.group(2))
            if start and end and start <= end:
                return {"application.start_date": start, "application.end_date": end}
    return {}


def _vacancy_total(title: str, text: str) -> int | None:
    title_counts = [
        int(value.replace(",", ""))
        for value in re.findall(r"\b([0-9][0-9,]*)\s+posts?\b", title, re.I)
    ]
    if title_counts:
        return sum(title_counts)
    match = re.search(
        r"(?:total|filling\s+up|recruitment\s+of)\s+(?:of\s+)?"
        r"([0-9][0-9,]*)\s+(?:vacancies|posts?)\b",
        text,
        re.I,
    )
    return int(match.group(1).replace(",", "")) if match else None


def _date_from_title(value: str) -> date | None:
    month_names = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    numeric = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", value)
    if numeric:
        return _parse_numeric_date(numeric.group(0))
    named = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*[, ]+(20\d{2})\b",
        value,
        re.I,
    )
    if named:
        return date(int(named.group(2)), month_names[named.group(1)[:3].casefold()], 1)
    return None


def _parse_numeric_date(value: str) -> date | None:
    match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", value)
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def _explicit_year(value: str) -> int | None:
    years = [int(year) for year in re.findall(r"\b20\d{2}\b", value)]
    return max(years) if years else None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
