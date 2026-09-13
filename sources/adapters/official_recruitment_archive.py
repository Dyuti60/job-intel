import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin

from pypdf import PdfReader

from app.models.candidates import CandidateValueType
from app.models.discovery import DocumentType
from app.models.source_registry import AuthorityType
from sources.adapters.apsc_recruitment import AdapterDocument, ParsedField
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


OFFICIAL_ARCHIVE_SOURCES = {
    "SLPRB_ASSAM": OfficialArchiveSource(
        source_code="SLPRB_ASSAM",
        authority_code="SLPRB_ASSAM",
        authority_name="State Level Police Recruitment Board, Assam",
        authority_type=AuthorityType.POLICE,
        listing_url="https://slprbassam.in/",
        adapter_key="official_archive_slprb",
        organization_name="State Level Police Recruitment Board, Assam",
    ),
    "DEE_ASSAM": OfficialArchiveSource(
        source_code="DEE_ASSAM",
        authority_code="DEE_ASSAM",
        authority_name="Directorate of Elementary Education, Assam",
        authority_type=AuthorityType.DEPARTMENT,
        listing_url="https://dee.assam.gov.in/portlets/recruitment-under-dee-assam",
        adapter_key="official_archive_dee",
        organization_name="Directorate of Elementary Education, Assam",
    ),
    "DME_ASSAM": OfficialArchiveSource(
        source_code="DME_ASSAM",
        authority_code="DME_ASSAM",
        authority_name="Directorate of Medical Education, Assam",
        authority_type=AuthorityType.DEPARTMENT,
        listing_url="https://dme.assam.gov.in/documents-detail/recruitment",
        adapter_key="official_archive_dme",
        organization_name="Directorate of Medical Education, Assam",
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
        for item in metadata:
            try:
                resource = self.http.fetch(item.document_url, accepted_types=("application/pdf",))
                fields = parse_official_advertisement_pdf(
                    resource.content,
                    item,
                    self.source.organization_name,
                )
                if not fields:
                    warnings.append(f"No supported fields extracted from {item.document_url}")
                notices.append(
                    ArchiveNotice(
                        metadata=item,
                        document=AdapterDocument(resource, DocumentType.PDF, "pdf"),
                        candidate_key=archive_candidate_key(self.source.authority_code, item),
                        fields=tuple(fields),
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
    pdf_links = [link for link in row.links if ".pdf" in link.url.casefold()]
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

    title_link = next((link for link in pdf_links if link.text), pdf_links[0])
    title = title_link.text or (row.cells[0] if row.cells else "")
    title = _clean_text(title)
    if not title:
        return None
    lowered = title.casefold()
    is_advertisement = lowered.startswith("advertisement") or lowered.startswith("recruitment")
    excluded = any(
        word in lowered
        for word in (
            "result",
            "select list",
            "shortlist",
            "verification",
            "withdrawal",
            "appointment",
            "answer key",
            "postponement",
        )
    )
    if not is_advertisement or excluded:
        return None
    return ArchiveNoticeMetadata(
        title=title,
        document_url=urljoin(source.listing_url, title_link.url),
        notification_number=None,
        notification_date=_date_from_title(title),
    )


def parse_official_advertisement_pdf(
    content: bytes,
    metadata: ArchiveNoticeMetadata,
    organization_name: str,
) -> list[ParsedField]:
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
    text = _clean_text("\n".join(text_parts))
    if not text:
        return []
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
    return [unique[path] for path in sorted(unique)]


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
