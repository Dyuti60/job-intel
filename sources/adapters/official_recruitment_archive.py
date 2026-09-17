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


def _metadata_from_row(row: _Row, source: OfficialArchiveSource) -> ArchiveNoticeMetadata | None:
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
    is_advertisement = any(word in lowered for word in ("advertisement", "recruitment", "vacancy"))
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
    return parse_official_advertisement_text("\n".join(text_parts), metadata, organization_name)


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
    application_mode = (
        "ONLINE"
        if re.search(r"online applications?", text, re.I)
        else "OFFLINE"
        if re.search(r"offline applications?", text, re.I)
        else None
    )
    if application_mode:
        fields.append(
            ParsedField(
                "application.mode",
                CandidateValueType.STRING,
                application_mode,
                application_mode.casefold(),
                locator,
                excerpt,
            )
        )
    fields.extend(_parse_recruitment_sections(raw_text))
    unique = {field.field_path: field for field in fields}
    posts, split_status, split_note, warnings = parse_vacancy_table(raw_text)
    if split_status == AdvertisementSplitStatus.LEGACY_UNSPLIT:
        posts, split_status, split_note, warnings = parse_narrative_vacancies(
            metadata.title, raw_text
        )
    if split_status == AdvertisementSplitStatus.EXPLICIT:
        posts, trade_ambiguities = refine_atomic_trade_posts(raw_text, posts)
        posts, ambiguities = apply_post_detail_tables(raw_text, posts)
        posts, whitespace_ambiguities = apply_whitespace_post_detail_tables(raw_text, posts)
        posts, text_ambiguities = apply_pypdf_post_details(raw_text, posts)
        ambiguities = (
            *trade_ambiguities,
            *ambiguities,
            *whitespace_ambiguities,
            *text_ambiguities,
        )
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


def extraction_diagnostic_summary(
    *,
    document_url: str,
    page_texts: list[str],
    extraction: ParsedAdvertisement,
) -> dict[str, object]:
    """Return a bounded development report without exposing document text."""
    recognized: list[dict[str, object]] = []
    unsupported: list[dict[str, object]] = []
    for page_number, page_text in enumerate(page_texts[:30], start=1):
        page_headings: list[str] = []
        for line in _source_lines(page_text):
            heading = _match_section_heading(line)
            if heading is not None:
                page_headings.append(heading[0])
            elif (
                len(unsupported) < 30
                and re.match(r"^\s*\d+(?:\.\d+)*\.?\s+[A-Z][A-Z /&()-]{4,}:?\s*$", line)
            ):
                unsupported.append({"page": page_number, "heading": _clean_text(line)[:160]})
        if page_headings:
            recognized.append(
                {"page": page_number, "sections": list(dict.fromkeys(page_headings))}
            )
    return {
        "document_url": document_url,
        "pages_scanned": min(len(page_texts), 30),
        "recognized_headings": recognized,
        "advertisement_field_paths": [field.field_path for field in extraction.fields],
        "posts": [
            {
                "post_key": post.post_key,
                "name": post.name,
                "fact_paths": [fact.field_path for fact in post.facts],
            }
            for post in extraction.posts
        ],
        "split_status": extraction.split_status.value,
        "ambiguities": list(extraction.warnings),
        "unsupported_section_headings": unsupported,
    }


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
    "essentialqualification": "qualification.essential",
    "qualification": "qualification.minimum",
    "desirablequalification": "qualification.desirable",
    "subject": "qualification.subject",
    "specialisation": "qualification.specialisation",
    "specialization": "qualification.specialisation",
    "recognizedboarduniversity": "qualification.recognised_institution_requirement",
    "recognisedboarduniversity": "qualification.recognised_institution_requirement",
    "technicalqualification": "qualification.technical",
    "registrationlicence": "qualification.registration_or_licence",
    "minimumpercentage": "qualification.minimum_percentage",
    "minimumgrade": "qualification.minimum_grade",
    "minimumage": "age.minimum",
    "maximumage": "age.maximum",
    "age": "age.range",
    "agereferencedate": "age.reference_date",
    "agecutoffdate": "age.reference_date",
    "agerelaxation": "age.relaxations",
    "payscale": "pay.scale",
    "gradepay": "pay.grade_pay",
    "paylevel": "pay.level",
    "fixedremuneration": "salary.fixed",
    "minimumexperience": "experience.minimum",
    "desirableexperience": "experience.desirable",
    "domicile": "domicile.requirement",
    "nationality": "nationality.requirement",
    "language": "language.requirement",
    "physicalstandards": "physical.criteria",
    "medicalstandards": "medical.criteria",
    "selectionprocess": "selection.process",
    "othereligibility": "eligibility.other",
}

_INTEGER_POST_FACTS = {"age.minimum", "age.maximum"}
_DATE_POST_FACTS = {"age.reference_date"}


_TRADE_GROUP_HEADING = re.compile(
    r"^(.+?)\s*(?::-|:)\s*The\s+Post\s+based\s+category\s+wise\s+distribution\b",
    re.I,
)
_TRADE_CATEGORY_PATTERNS = (
    ("UR", r"\bUR\b", "vacancies.ur"),
    ("OBC/MOBC", r"\bOBC\s*/\s*MOBC\b", "vacancies.obc_mobc"),
    (
        "Tea Tribes & Adivasi",
        r"\bTea\s+Tribes\s*&\s*Adivasi\b",
        "vacancies.tea_tribes_adivasi",
    ),
    ("SC", r"\bSC\b", "vacancies.sc"),
    ("ST(P)", r"\bST\s*\(P\)", "vacancies.st_p"),
    ("ST(H)", r"\bST\s*\(H\)", "vacancies.st_h"),
    ("EWS", r"\bEWS\b", "vacancies.ews"),
)


def refine_atomic_trade_posts(
    raw_text: str, posts: tuple[ParsedPost, ...]
) -> tuple[tuple[ParsedPost, ...], tuple[str, ...]]:
    """Replace intermediate organisation Posts with reconciled trade roster rows."""
    lines = _source_lines(raw_text)
    starts = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := _TRADE_GROUP_HEADING.match(line))
    ]
    if not starts:
        return posts, ()
    replacements: dict[int, list[ParsedPost]] = {}
    ambiguities: list[str] = []
    for occurrence, (start, match) in enumerate(starts, start=1):
        end = starts[occurrence][0] if occurrence < len(starts) else len(lines)
        section_end = next(
            (
                index
                for index in range(start + 1, end)
                if _match_kind(lines[index]) == "eligibility"
            ),
            end,
        )
        heading_organisation = _clean_text(match.group(1)).strip(" :-")
        parent_matches = [
            index
            for index, post in enumerate(posts)
            if _canonical_owner(_post_organisation(post))
            == _canonical_owner(heading_organisation)
        ]
        locator = f"pdf:trade-roster;occurrence={occurrence}"
        if len(parent_matches) != 1:
            ambiguities.append(
                f"Trade roster at {locator} matches {len(parent_matches)} organisation Posts"
            )
            continue
        parent_index = parent_matches[0]
        organisation = _post_organisation(posts[parent_index])
        rows, error = _parse_trade_roster_rows(lines[start + 1 : section_end])
        parent_total = next(
            (
                int(fact.value)
                for fact in posts[parent_index].facts
                if fact.field_path == "vacancies.total"
            ),
            None,
        )
        if error or not rows or parent_total != sum(row[1] for row in rows):
            ambiguities.append(error or f"Trade roster at {locator} does not reconcile")
            continue
        children: list[ParsedPost] = []
        for row_number, (trade_name, total, categories) in enumerate(rows, start=1):
            row_locator = f"{locator};row={row_number}"
            display_name = f"{trade_name} - {organisation}"
            facts: list[ParsedField] = [
                ParsedField(
                    "name", CandidateValueType.STRING, display_name, trade_name,
                    f"{row_locator};field=post", trade_name,
                ),
                ParsedField(
                    "organisation.name", CandidateValueType.STRING, organisation,
                    organisation, f"{row_locator};field=organisation", organisation,
                ),
                ParsedField(
                    "vacancies.total", CandidateValueType.INTEGER, total, str(total),
                    f"{row_locator};field=total", str(total),
                ),
            ]
            men = sum(category["male"] for category in categories)
            women = sum(category["female"] for category in categories)
            category_gender = [
                {key: value for key, value in category.items() if key != "path"}
                for category in categories
            ]
            facts.extend(
                (
                    ParsedField(
                        "vacancies.men", CandidateValueType.INTEGER, men, str(men),
                        f"{row_locator};field=men", str(men),
                    ),
                    ParsedField(
                        "vacancies.women", CandidateValueType.INTEGER, women, str(women),
                        f"{row_locator};field=women", str(women),
                    ),
                    ParsedField(
                        "vacancies.category_gender", CandidateValueType.JSON, category_gender,
                        str(category_gender), f"{row_locator};field=category-gender",
                        str(category_gender),
                    ),
                )
            )
            for category in categories:
                facts.append(
                    ParsedField(
                        category["path"], CandidateValueType.INTEGER, category["total"],
                        str(category["total"]), f"{row_locator};field={category['path']}",
                        str(category),
                    )
                )
            children.append(
                ParsedPost(
                    post_key=_stable_post_key(trade_name, organisation),
                    ordinal=0,
                    name=display_name,
                    normalized_name=" ".join(trade_name.casefold().split()),
                    source_locator=row_locator,
                    facts=tuple(sorted(facts, key=lambda fact: fact.field_path)),
                )
            )
        replacements[parent_index] = children
    if ambiguities or len(replacements) != len(starts):
        return posts, tuple(ambiguities or ["Trade rosters could not be decomposed completely"])
    refined: list[ParsedPost] = []
    for index, post in enumerate(posts):
        refined.extend(replacements.get(index, [post]))
    if len({post.post_key for post in refined}) != len(refined):
        return posts, ("Trade rosters produce duplicate stable Post identities",)
    refined = [replace(post, ordinal=ordinal) for ordinal, post in enumerate(refined, start=1)]
    refined_posts, qualification_ambiguities = _attach_trade_requirements(lines, tuple(refined))
    return refined_posts, qualification_ambiguities


def _parse_trade_roster_rows(
    lines: list[str],
) -> tuple[list[tuple[str, int, list[dict[str, object]]]], str | None]:
    header_text = " ".join(lines[:8])
    category_matches = sorted(
        (
            match.start(),
            label,
            path,
        )
        for label, pattern, path in _TRADE_CATEGORY_PATTERNS
        if (match := re.search(pattern, header_text, re.I))
    )
    categories = [(label, path) for _position, label, path in category_matches]
    if not categories:
        return [], "Trade roster has no deterministic category header"
    rows: list[tuple[str, int, list[dict[str, object]]]] = []
    pending_name: list[str] = []
    for line in lines:
        if _match_section_heading(line) is not None:
            break
        if re.match(
            r"^(?:Name\s+of|Posts?$|UR\b|&\s*Adivasi\b|TOTAL\b|M\s+F\b)",
            line,
            re.I,
        ):
            continue
        numbers = [int(value) for value in re.findall(r"\b\d+\b", line)]
        if not numbers:
            if re.fullmatch(r"[A-Za-z][A-Za-z ]+", line):
                pending_name.append(_clean_text(line))
            continue
        first_number = re.search(r"\b\d+\b", line)
        assert first_number is not None
        prefix = _clean_text(line[: first_number.start()])
        trade_name = _clean_text(" ".join((*pending_name, prefix)))
        pending_name = []
        expected_values = len(categories) * 2
        if len(numbers) not in {expected_values, expected_values + 1} or not trade_name:
            return [], "Trade roster row has an unsupported whitespace shape"
        gender_values = numbers[:expected_values]
        total = numbers[-1] if len(numbers) == expected_values + 1 else sum(gender_values)
        category_rows = [
            {
                "category": label,
                "path": path,
                "male": gender_values[index * 2],
                "female": gender_values[index * 2 + 1],
                "total": gender_values[index * 2] + gender_values[index * 2 + 1],
            }
            for index, (label, path) in enumerate(categories)
        ]
        if sum(int(category["total"]) for category in category_rows) != total:
            return [], "Trade roster category/gender values do not reconcile to the row total"
        rows.append((trade_name, total, category_rows))
    return rows, None


def _attach_trade_requirements(
    lines: list[str], posts: tuple[ParsedPost, ...]
) -> tuple[tuple[ParsedPost, ...], tuple[str, ...]]:
    start = next(
        (index for index, line in enumerate(lines) if _match_kind(line) == "qualification"),
        None,
    )
    end = next(
        (
            index
            for index, line in enumerate(lines)
            if start is not None and index > start and _match_kind(line) == "physical"
        ),
        None,
    )
    if start is None or end is None:
        return posts, ()
    labels = {
        post.normalized_name
        for post in posts
    }
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start:end]:
        match = re.fullmatch(r"(.+?)\s*:-\s*", line)
        normalized = " ".join(match.group(1).casefold().split()) if match else ""
        if normalized in labels:
            current = normalized
            blocks.setdefault(current, [])
        elif current is not None:
            if re.match(r"^\d+(?:\.\d+)+", line):
                current = None
            else:
                blocks[current].append(line)
    fact_maps = [{fact.field_path: fact for fact in post.facts} for post in posts]
    for trade_name, block in blocks.items():
        text = _clean_text(" ".join(block)).strip(" .")
        if not text:
            continue
        facts = [
            ParsedField(
                "qualification.additional", CandidateValueType.STRING, text, text,
                f"pdf:trade-requirement={trade_name}", text[:8000],
            )
        ]
        certificate = re.search(
            r"((?:Training\s+Certificate|Minimum\s+one\s+year\s+Certificate\s+course)"
            r".+?(?:5\s+marks|$))",
            text,
            re.I,
        )
        if certificate:
            facts.append(
                ParsedField(
                    "qualification.certificate", CandidateValueType.STRING,
                    _clean_text(certificate.group(1)), certificate.group(1),
                    f"pdf:trade-requirement={trade_name};field=certificate", text[:8000],
                )
            )
        experience = re.search(
            r"((?:Minimum\s+\d+\s*\([^)]*\)\s+year|Two\s+years?)\s+"
            r"(?:working\s+)?experience.+?(?:5\s+marks|Institution))",
            text,
            re.I,
        )
        if experience:
            facts.append(
                ParsedField(
                    "experience.requirement", CandidateValueType.STRING,
                    _clean_text(experience.group(1)), experience.group(1),
                    f"pdf:trade-requirement={trade_name};field=experience", text[:8000],
                )
            )
        indexes = [
            index for index, post in enumerate(posts) if post.normalized_name == trade_name
        ]
        _attach_post_facts(fact_maps, indexes, tuple(facts), [], f"pdf:trade={trade_name}")
    updated = tuple(
        replace(post, facts=tuple(facts[path] for path in sorted(facts)))
        for post, facts in zip(posts, fact_maps, strict=True)
    )
    return updated, ()


def apply_whitespace_post_detail_tables(
    raw_text: str, posts: tuple[ParsedPost, ...]
) -> tuple[tuple[ParsedPost, ...], tuple[str, ...]]:
    """Attach bounded Post details from aligned pypdf columns without pipe delimiters."""
    lines = raw_text.replace("\r\n", "\n").split("\n")
    fact_maps = [{fact.field_path: fact for fact in post.facts} for post in posts]
    ambiguities: list[str] = []
    for header_index, line in enumerate(lines):
        columns = _aligned_columns(line)
        mapped = {
            index: _POST_DETAIL_HEADERS[key]
            for index, (_start, heading) in enumerate(columns)
            if (key := _header_key(heading)) in _POST_DETAIL_HEADERS
        }
        detail_paths = {
            path
            for path in mapped.values()
            if path not in {"post_name", "organisation", "department"}
        }
        if "post_name" not in mapped.values() or not detail_paths:
            continue
        starts = [start for start, _heading in columns]
        rows = _aligned_detail_rows(lines, header_index, starts, mapped, posts)
        for row_number, values in enumerate(rows, start=1):
            locator = f"pdf:whitespace-table=post-details-{header_index + 1};row={row_number}"
            matches = _matching_post_indexes(posts, values)
            if len(matches) != 1:
                ambiguities.append(
                    f"Whitespace Post detail row at {locator} matches {len(matches)} Posts"
                )
                continue
            facts: list[ParsedField] = []
            excerpt = " | ".join(values.get(path, "") for path in mapped.values())[:8000]
            for path in sorted(detail_paths):
                raw_value = _clean_text(values.get(path, ""))
                if not raw_value or raw_value in {"-", "—"}:
                    continue
                if path == "age.range":
                    age_match = re.fullmatch(
                        r"(\d{1,3})\s*(?:to|-|and)\s*(\d{1,3})(?:\s*years?)?",
                        raw_value,
                        re.I,
                    )
                    if age_match is None:
                        ambiguities.append(
                            f"Whitespace Post age at {locator} is not an exact range"
                        )
                        continue
                    for age_path, group in (("age.minimum", 1), ("age.maximum", 2)):
                        facts.append(
                            ParsedField(
                                age_path,
                                CandidateValueType.INTEGER,
                                int(age_match.group(group)),
                                raw_value,
                                f"{locator};column=age",
                                excerpt,
                            )
                        )
                    continue
                facts.append(
                    ParsedField(
                        path,
                        CandidateValueType.STRING,
                        raw_value,
                        raw_value,
                        f"{locator};column={path}",
                        excerpt,
                    )
                )
            _attach_post_facts(fact_maps, matches, tuple(facts), ambiguities, locator)
    updated = tuple(
        replace(post, facts=tuple(facts[path] for path in sorted(facts)))
        for post, facts in zip(posts, fact_maps, strict=True)
    )
    return updated, tuple(ambiguities)


def _aligned_columns(line: str) -> list[tuple[int, str]]:
    if "|" in line or not re.search(r"\S\s{2,}\S", line):
        return []
    return [
        (match.start(), _clean_text(match.group(0)))
        for match in re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|$)", line.rstrip())
    ]


def _aligned_detail_rows(
    lines: list[str],
    header_index: int,
    starts: list[int],
    mapped: dict[int, str],
    posts: tuple[ParsedPost, ...],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in lines[header_index + 1 : header_index + 51]:
        if not line.strip():
            if current:
                rows.append(current)
                current = None
            if rows:
                break
            continue
        cells = [
            line[start : starts[index + 1] if index + 1 < len(starts) else None].strip()
            for index, start in enumerate(starts)
        ]
        values = {mapped[index]: cells[index] for index in mapped if index < len(cells)}
        post_name = _clean_text(values.get("post_name", ""))
        if post_name:
            if not _matching_post_indexes(posts, values):
                if current:
                    rows.append(current)
                break
            if current:
                rows.append(current)
            current = values
        elif current:
            for path, value in values.items():
                if path == "post_name" or not value:
                    continue
                current[path] = _clean_text(f"{current.get(path, '')} {value}")
    if current:
        rows.append(current)
    return rows


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


_SECTION_HEADINGS = {
    "eligibility criteria": "eligibility",
    "educational qualification": "qualification",
    "education qualification": "qualification",
    "educational standards": "qualification",
    "educational and other qualification required": "qualification",
    "educational qualification other mandatory requirement": "qualification",
    "qualification": "qualification",
    "age": "age",
    "age criteria": "age",
    "age limit": "age",
    "age relaxation": "age_relaxation",
    "relaxation in age": "age_relaxation",
    "relaxations": "age_relaxation",
    "domicile residency": "domicile",
    "domicile": "domicile",
    "residency": "domicile",
    "nationality": "nationality",
    "experience": "experience",
    "pay scale": "pay",
    "salary pay scale": "pay",
    "remuneration": "pay",
    "physical standards": "physical",
    "physical standard": "physical",
    "physical standard test": "physical",
    "physical efficiency test": "physical",
    "pst pet": "physical",
    "medical standards": "medical",
    "medical standard": "medical",
    "medical fitness": "medical",
    "reservation": "reservation",
    "reservation of vacancies": "reservation",
    "application fee": "application_fee",
    "how to apply": "application_steps",
    "application procedure": "application_steps",
    "application process": "application_steps",
    "where to apply": "application_location",
    "application portal": "application_location",
    "documents required": "documents",
    "documents to be uploaded": "documents",
    "documents": "documents",
    "certificates documents": "documents",
    "selection process": "selection",
    "selection procedure": "selection",
    "recruitment process": "selection",
    "phases of recruitment tests": "selection",
    "mode of selection": "selection",
    "scheme of examination": "exam_pattern",
    "exam pattern": "exam_pattern",
    "examination pattern": "exam_pattern",
    "written test": "exam_pattern",
    "syllabus": "syllabus",
    "other eligibility conditions": "other_eligibility",
    "eligibility conditions": "other_eligibility",
    "general instructions": "instructions",
    "important instructions": "instructions",
}


def _parse_recruitment_sections(raw_text: str) -> list[ParsedField]:
    """Extract only explicitly headed, structurally bounded recruitment facts."""
    sections = _bounded_sections(raw_text)
    parsed: list[ParsedField] = []
    for section_number, (kind, heading, lines) in enumerate(sections, start=1):
        excerpt = "\n".join((heading, *lines))[:8000]
        locator = f"pdf:section={kind};occurrence={section_number}"
        if kind == "eligibility":
            parsed.extend(_eligibility_fields(lines, locator, excerpt))
        elif kind == "qualification":
            parsed.extend(_qualification_fields(lines, locator, excerpt))
        elif kind == "age":
            parsed.extend(_age_fields(lines, locator, excerpt))
        elif kind == "age_relaxation":
            parsed.extend(_age_relaxation_fields(lines, locator, excerpt))
        elif kind == "domicile":
            parsed.extend(_text_section_field("domicile.requirement", lines, locator, excerpt))
        elif kind == "nationality":
            parsed.extend(_text_section_field("nationality.requirement", lines, locator, excerpt))
        elif kind == "experience":
            parsed.extend(_labeled_or_text_fields("experience", lines, locator, excerpt))
        elif kind == "pay":
            parsed.extend(_labeled_or_text_fields("pay", lines, locator, excerpt))
        elif kind == "physical":
            pass
        elif kind == "medical":
            parsed.extend(_structured_section_field("medical.criteria", lines, locator, excerpt))
        elif kind == "reservation":
            parsed.extend(
                _structured_section_field(
                    "reservation.details", lines, locator, excerpt, prefer_table=True
                )
            )
        elif kind == "application_fee":
            parsed.extend(_application_fee_fields(lines, locator, excerpt))
        elif kind == "application_steps":
            application_lines = _exclude_embedded_physical_table(lines)
            parsed.extend(
                _list_section_field("application.steps", application_lines, locator, excerpt)
            )
        elif kind == "application_location":
            parsed.extend(
                _text_section_field("application.where_to_apply", lines, locator, excerpt)
            )
        elif kind == "documents":
            parsed.extend(
                _list_section_field("application.documents_required", lines, locator, excerpt)
            )
        elif kind == "selection":
            pass
        elif kind == "exam_pattern":
            parsed.extend(_exam_fields(lines, locator, excerpt))
        elif kind == "syllabus":
            parsed.extend(
                _structured_section_field(
                    "syllabus.phases", lines, locator, excerpt, prefer_table=True
                )
            )
        elif kind == "other_eligibility":
            parsed.extend(_list_section_field("eligibility.other", lines, locator, excerpt))
        elif kind == "instructions":
            parsed.extend(_list_section_field("instructions.important", lines, locator, excerpt))

    parsed.extend(_physical_fields(raw_text))
    parsed.extend(_selection_fields(raw_text))
    parsed.extend(_inline_application_fee(raw_text))
    parsed.extend(_inline_pay_fields(raw_text))

    application_url = re.search(
        r"(?:application\s+(?:url|portal|website)|apply\s+(?:online\s+)?at|where\s+to\s+apply)"
        r"\s*[:.-]?\s*(https?://[^\s<>]+)",
        raw_text,
        re.I,
    )
    if application_url:
        url = application_url.group(1).rstrip(".,);]")
        parsed.append(
            ParsedField(
                "application.url",
                CandidateValueType.STRING,
                url,
                url,
                "pdf:label=application-url",
                application_url.group(0)[:8000],
            )
        )
    unique: dict[str, ParsedField] = {}
    conflicts: set[str] = set()
    for field in parsed:
        existing = unique.get(field.field_path)
        if existing is not None and (
            existing.value_type != field.value_type or existing.value != field.value
        ):
            conflicts.add(field.field_path)
            unique.pop(field.field_path, None)
        elif field.field_path not in conflicts:
            unique[field.field_path] = field
    return [unique[path] for path in sorted(unique)]


def _bounded_sections(raw_text: str) -> list[tuple[str, str, list[str]]]:
    sections: list[tuple[str, str, list[str]]] = []
    current: tuple[str, str, list[str]] | None = None
    for line in _source_lines(raw_text):
        heading = _match_section_heading(line)
        if heading is not None:
            if current is not None:
                sections.append(current)
            kind, title, inline_content = heading
            current = (kind, title, [inline_content] if inline_content else [])
        elif current is not None:
            current[2].append(line)
    if current is not None:
        sections.append(current)
    return sections


def _source_lines(raw_text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in raw_text.replace("\r\n", "\n").split("\n"):
        line = _clean_text(raw_line)
        if not line or re.fullmatch(r"Page\s+\d+\s+of\s+\d+", line, re.I):
            continue
        if line in {
            "STATE LEVEL POLICE RECRUITMENT BOARD, ASSAM",
            "REHABARI, GUWAHATI �781008",
        }:
            continue
        lines.append(line)
    return lines


def _match_section_heading(line: str) -> tuple[str, str, str] | None:
    number = re.match(r"^\s*(\d+(?:\.\d+)*(?:\.[A-Z])?)\.?\s*", line, re.I)
    without_number = line[number.end() :] if number else line
    for alias in sorted(_SECTION_HEADINGS, key=len, reverse=True):
        pattern = r"^" + r"[\s&/()-]+".join(re.escape(part) for part in alias.split())
        match = re.match(pattern + r"(?=\s*[:.-]|\s*$)", without_number, re.I)
        if match is None:
            continue
        remainder = without_number[match.end() :].lstrip(" :-.")
        if (
            number
            and "." not in number.group(1)
            and without_number != without_number.upper()
        ):
            return None
        if number is None and line.rstrip().endswith(".") and line != line.upper():
            return None
        return _SECTION_HEADINGS[alias], without_number[: match.end()].strip(), remainder
    return None


def _eligibility_fields(
    lines: list[str], locator: str, excerpt: str
) -> list[ParsedField]:
    text = " ".join(lines)
    claims = (
        (
            "nationality.requirement",
            r"(?:Applicant|Candidate)s?\s+must\s+be\s+(?:a\s+)?Citizen\s+of\s+India",
        ),
        (
            "domicile.requirement",
            r"(?:Applicant|Candidate)s?\s+must\s+be.{0,40}?Permanent\s+Resident\s+of\s+Assam",
        ),
        (
            "registration.employment_exchange",
            r"(?:Applicant|Candidate)s?\s+must\s+be\s+registered\s+with\s+"
            r"a\s+local\s+Employment\s+Exchange\s+in\s+Assam",
        ),
        (
            "language.requirement",
            r"(?:Applicant|Candidate)s?\s+must\s+speak\s+"
            r"Assamese\s+or\s+any\s+other\s+State\s+language\s+fluently",
        ),
    )
    parsed: list[ParsedField] = []
    for path, pattern in claims:
        match = re.search(pattern, text, re.I)
        if match:
            parsed.extend(_string_field(path, match.group(0), locator, excerpt))
    return parsed


def _age_relaxation_fields(
    lines: list[str], locator: str, excerpt: str
) -> list[ParsedField]:
    text = " ".join(lines)
    rules: list[dict[str, str]] = []
    patterns = (
        (
            r"SC,?\s*ST\s*\(P\)\s*and\s*ST\s*\(H\)\s+(\d+)\s+years",
            "SC / ST(P) / ST(H)",
        ),
        (r"OBC\s*/\s*MOBC\s+(\d+)\s+years", "OBC / MOBC"),
        (
            r"Trained\s+Home\s+Guards.{0,220}?Additional\s+(\d+)\s*"
            r"(?:\([^)]*\)\s*)?years",
            "Trained Home Guards",
        ),
        (
            r"Ex[ -]?Servicemen.{0,160}?Additional\s+(\d+)\s*"
            r"(?:\([^)]*\)\s*)?years",
            "Ex-servicemen",
        ),
        (r"PwBD.{0,100}?(\d+)\s+years", "PwBD"),
    )
    for pattern, category in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            rules.append({"category": category, "relaxation": f"{match.group(1)} years"})
    if rules:
        return [
            ParsedField(
                "age.relaxations",
                CandidateValueType.JSON,
                rules,
                "\n".join(lines),
                locator,
                excerpt,
            )
        ]
    return _structured_section_field(
        "age.relaxations", lines, locator, excerpt, prefer_table=True
    )


def _match_kind(line: str) -> str | None:
    heading = _match_section_heading(line)
    return heading[0] if heading is not None else None


def _physical_fields(raw_text: str) -> list[ParsedField]:
    lines = _source_lines(raw_text)
    start = next(
        (index for index, line in enumerate(lines) if _match_kind(line) == "physical"), None
    )
    end = next(
        (
            index
            for index, line in enumerate(lines)
            if start is not None and index > start and _match_kind(line) == "application_steps"
        ),
        None,
    )
    if start is None or end is None:
        return []
    bounded = lines[start:end]
    height, chest = _physical_tables(lines)
    other = [
        line
        for line in bounded
        if re.search(r"\b(?:weight|physically\s+fit|positive\s+aptitude)\b", line, re.I)
    ]
    if height or chest:
        value = {"height": height, "chest": chest, "other": _clean_list(other)}
        excerpt = "\n".join(
            (*bounded, *[str(item) for item in height], *[str(item) for item in chest])
        )
        return [
            ParsedField(
                "physical.criteria", CandidateValueType.JSON, value, str(value),
                "pdf:section=physical-standards", excerpt[:8000],
            )
        ]
    useful = [
        line
        for line in bounded
        if re.search(
            r"\b(?:height|chest|expansion|weight|race|running|long\s+jump|high\s+jump|"
            r"walking|cycling|swimming|PST|PET|cm|metres?|minutes?)\b",
            line,
            re.I,
        )
    ]
    if not useful:
        return []
    excerpt = "\n".join(bounded)[:8000]
    return [
        ParsedField(
            "physical.criteria",
            CandidateValueType.JSON,
            _ordered_items(useful),
            "\n".join(useful),
            "pdf:section=physical-standards",
            excerpt,
        )
    ]


def _physical_tables(lines: list[str]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    height: list[dict[str, object]] = []
    chest: list[dict[str, object]] = []
    height_start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.fullmatch(r"Sl\.\s*No\.\s+Categories\s+Male\s+Female", line, re.I)
        ),
        None,
    )
    chest_start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.fullmatch(r"Sl\.\s*No\.\s+Categories\s+Normal\s+Expansion", line, re.I)
        ),
        None,
    )
    if height_start is not None:
        stop = chest_start if chest_start is not None else min(len(lines), height_start + 10)
        for line in lines[height_start + 1 : stop]:
            match = re.fullmatch(
                r"\([a-z]\)\s+(.+?)\s+(\d+(?:\.\d+)?\s*cm)\s+"
                r"(\d+(?:\.\d+)?\s*cm)",
                line,
                re.I,
            )
            if match:
                height.append(
                    {
                        "categories": _clean_text(match.group(1)),
                        "male": _clean_text(match.group(2)),
                        "female": _clean_text(match.group(3)),
                    }
                )
    if chest_start is not None:
        pending_categories: str | None = None
        for line in lines[chest_start + 1 : chest_start + 10]:
            inline = re.fullmatch(
                r"\([a-z]\)\s+(.+?)\s+(Min\.\s*\d+(?:\.\d+)?\s*cm)\s+"
                r"(\+\s*\d+(?:\.\d+)?\s*cm)",
                line,
                re.I,
            )
            if inline:
                chest.append(
                    {
                        "categories": _clean_text(inline.group(1)),
                        "normal": _clean_text(inline.group(2)),
                        "expansion": _clean_text(inline.group(3)),
                    }
                )
                pending_categories = None
                continue
            category = re.fullmatch(r"\([a-z]\)\s+(.+)", line, re.I)
            if category:
                pending_categories = _clean_text(category.group(1))
                continue
            values = re.fullmatch(
                r"(Min\.\s*\d+(?:\.\d+)?\s*cm)\s+(\+\s*\d+(?:\.\d+)?\s*cm)",
                line,
                re.I,
            )
            if values and pending_categories:
                chest.append(
                    {
                        "categories": pending_categories,
                        "normal": _clean_text(values.group(1)),
                        "expansion": _clean_text(values.group(2)),
                    }
                )
                pending_categories = None
            elif pending_categories and re.fullmatch(r"[A-Za-z() /&]+", line):
                pending_categories = _clean_text(f"{pending_categories} {line}")
    return height, chest


def _exclude_embedded_physical_table(lines: list[str]) -> list[str]:
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.fullmatch(r"Sl\.\s*No\.\s+Categories\s+Male\s+Female", line, re.I)
        ),
        None,
    )
    if start is None:
        return lines
    end = next(
        (
            index
            for index, line in enumerate(lines[start + 1 :], start=start + 1)
            if re.match(r"^\(?[ivxlcdm]+[.)]\s+", line, re.I)
        ),
        len(lines),
    )
    return [*lines[:start], *lines[end:]]


def _selection_fields(raw_text: str) -> list[ParsedField]:
    lines = _source_lines(raw_text)
    stages = (
        (r"^7\.1\s+PRELIMINARY\s+IDENTITY\s+VERIFICATION\b", "Preliminary Identity Verification"),
        (r"^7\.3\s+MEDICAL\s+EXAMINATION\b", "Medical Examination"),
        (r"^7\.4\s+PHYSICAL\s+STANDARD\s+TEST\b", "Physical Standard Test (PST)"),
        (r"^7\.5\s+TRADE\s+PROFICIENCY\s+TEST\b", "Trade Proficiency Test (TPT)"),
        (r"^8\.\s+FINAL\s+MERIT\s+LISTS?\b", "Final Merit List"),
    )
    phase_names = [
        name
        for line in lines
        for pattern, name in stages
        if re.search(pattern, line, re.I)
    ]
    phases = [
        {"sequence": sequence, "name": name}
        for sequence, name in enumerate(phase_names, start=1)
    ]
    if len(phases) >= 2:
        parsed = [
            ParsedField(
                "selection.phases", CandidateValueType.JSON, phases, str(phases),
                "pdf:section=selection-stages", str(phases),
            )
        ]
        text = " ".join(lines)
        marks = re.search(r"7\.5\s+TRADE\s+PROFICIENCY\s+TEST\s*:\s*(\d+)\s+Marks", text, re.I)
        if marks:
            value = {"maximum_marks": int(marks.group(1))}
            parsed.append(
                ParsedField(
                    "selection.trade_proficiency_test", CandidateValueType.JSON, value,
                    marks.group(0), "pdf:section=trade-proficiency-test", marks.group(0),
                )
            )
        maximum = re.search(r"Maximum\s+Marks\s*:\s*(\d+)", text, re.I)
        qualifying = re.search(r"Passed\s+Marks\s*:\s*(\d+)%", text, re.I)
        if maximum or qualifying:
            value = {}
            if maximum:
                value["maximum_marks"] = int(maximum.group(1))
            if qualifying:
                value["qualifying_percentage"] = int(qualifying.group(1))
            parsed.append(
                ParsedField(
                    "selection.final_merit", CandidateValueType.JSON, value, str(value),
                    "pdf:section=final-merit", str(value),
                )
            )
        return parsed
    selection = next(
        (
            (heading, section_lines)
            for kind, heading, section_lines in _bounded_sections(raw_text)
            if kind == "selection"
        ),
        None,
    )
    if selection is None:
        return []
    heading, section_lines = selection
    return _ordered_structured_field(
        "selection.phases", section_lines, "pdf:section=selection", heading
    )


def _inline_application_fee(raw_text: str) -> list[ParsedField]:
    match = re.search(r"\bThere\s+will\s+be\s+no\s+Application\s+Fee\b", raw_text, re.I)
    if not match:
        return []
    return _string_field(
        "application.fee",
        "No application fee",
        "pdf:label=application-fee",
        match.group(0),
    )


def _inline_pay_fields(raw_text: str) -> list[ParsedField]:
    text = _clean_text(raw_text)
    match = re.search(
        r"\bin\s+the\s+Pay\s+Scale\s+of\s+"
        r"(Rs\.?\s*[0-9, ]+\s*[-–]\s*[0-9, ]+/-?)"
        r"(?:\s*\([^)]*\))?",
        text,
        re.I,
    )
    if not match:
        return []
    return _string_field("pay.scale", match.group(1), "pdf:label=pay-scale", match.group(0))


def _exam_fields(lines: list[str], locator: str, excerpt: str) -> list[ParsedField]:
    table = _section_table(lines)
    if table:
        return [
            ParsedField(
                "selection.exam_pattern",
                CandidateValueType.JSON,
                table,
                "\n".join(lines),
                locator,
                excerpt,
            )
        ]
    text = " ".join(lines)
    pattern: dict[str, object] = {"phase": "Written Test"}
    questions = re.search(r"(\d+)\s+multiple\s+choice\s+type\s+questions", text, re.I)
    marks = re.search(
        r"Total\s+marks\s+for\s+the\s+Written\s+Test\s+will\s+be\s+(\d+)", text, re.I
    )
    duration = re.search(
        r"(?:duration|time)\s*[:.-]?\s*(\d+\s*(?:hours?|minutes?))", text, re.I
    )
    if questions:
        pattern["questions"] = int(questions.group(1))
    if marks:
        pattern["marks"] = int(marks.group(1))
    if duration:
        pattern["duration"] = _clean_text(duration.group(1))
    if re.search(r"\bno\s+negative\s+marking\b", text, re.I):
        pattern["negative_marking"] = "None"
    if re.search(r"\bOMR\s+answer\s+sheet\b", text, re.I):
        pattern["mode"] = "OMR answer sheet"
    if re.search(r"question\s+paper.+?following\s+languages", text, re.I):
        language_line = next(
            (
                line
                for line in lines
                if re.fullmatch(
                    r"(?:Assamese|Bodo|Bengali|English)(?:\s*/\s*"
                    r"(?:Assamese|Bodo|Bengali|English))+\.?",
                    line,
                    re.I,
                )
            ),
            None,
        )
        if language_line:
            pattern["languages"] = [
                language.strip().title()
                for language in language_line.rstrip(".").split("/")
            ]
    subjects = _subjects_from_exam_lines(lines)
    parsed: list[ParsedField] = []
    if len(pattern) > 1:
        parsed.append(
            ParsedField(
                "selection.exam_pattern",
                CandidateValueType.JSON,
                [pattern],
                "\n".join(lines),
                locator,
                excerpt,
            )
        )
    if subjects:
        parsed.append(
            ParsedField(
                "syllabus.phases",
                CandidateValueType.JSON,
                [{"phase": "Written Test", "subjects": subjects}],
                "\n".join(lines),
                locator,
                excerpt,
            )
        )
    return parsed


def _subjects_from_exam_lines(lines: list[str]) -> list[str]:
    start = next(
        (index for index, line in enumerate(lines) if "subjects to be covered" in line.casefold()),
        None,
    )
    if start is None:
        return []
    selected: list[str] = []
    for line in lines[start + 1 : start + 15]:
        if "question paper" in line.casefold() or re.match(r"^\d+(?:\.\d+)", line):
            break
        match = re.match(r"^\s*(?:\(?[ivxlcdm]+[.)])\s*(.+)$", line, re.I)
        if match:
            selected.append(_clean_text(match.group(1)))
        elif selected:
            selected[-1] = _clean_text(f"{selected[-1]} {line}")
    return selected


def _qualification_fields(lines: list[str], locator: str, excerpt: str) -> list[ParsedField]:
    labels = {
        "minimum": "qualification.minimum",
        "essential": "qualification.essential",
        "desirable": "qualification.desirable",
        "subject": "qualification.subject",
        "specialisation": "qualification.specialisation",
        "specialization": "qualification.specialisation",
        "technical": "qualification.technical",
        "recognised institution": "qualification.recognised_institution_requirement",
        "recognized institution": "qualification.recognised_institution_requirement",
        "registration licence": "qualification.registration_or_licence",
        "registration license": "qualification.registration_or_licence",
    }
    result: list[ParsedField] = []
    unlabeled: list[str] = []
    for line in lines:
        match = re.match(r"([^:]{2,50}):\s*(.+)$", line)
        key = re.sub(r"[^a-z]+", " ", match.group(1).casefold()).strip() if match else ""
        path = labels.get(key)
        if match and path:
            result.extend(_string_field(path, match.group(2), locator, excerpt))
        elif not line.startswith("|"):
            unlabeled.append(line)
    if not result and unlabeled:
        text = " ".join(unlabeled)
        minimum = re.search(
            r"\b(?:Minimum\s+)?(?:Class\s+(?:VI|VIII|IX|X|XII)|HSLC|HSSLC|"
            r"Bachelor(?:'s)?|Master(?:'s)?|Graduate|Diploma|Degree)\b"
            r".{0,240}?(?:recognized|recognised)\s+(?:School|Board|Council|"
            r"Institution|University)(?:\s+or\s+(?:Institution|Council))?",
            text,
            re.I,
        )
        if minimum:
            result.extend(
                _string_field("qualification.minimum", minimum.group(0), locator, excerpt)
            )
        maximum = re.search(
            r"maximum\s+qualification\s+(?:will\s+)?be\s+(.{1,180}?"
            r"(?:recognized|recognised)\s+(?:Board|Council|Institution|University)"
            r"(?:\s+or\s+(?:Board|Council|Institution|University))?)",
            text,
            re.I,
        )
        if maximum:
            result.extend(
                _string_field("qualification.maximum", maximum.group(1), locator, excerpt)
            )
    return result


def _age_fields(lines: list[str], locator: str, excerpt: str) -> list[ParsedField]:
    text = " ".join(lines)
    result: list[ParsedField] = []
    for label, path in (("minimum", "age.minimum"), ("maximum", "age.maximum")):
        match = re.search(rf"\b{label}(?:\s+age)?\s*:\s*(\d{{1,3}})(?:\s*years?)?\b", text, re.I)
        if match:
            result.append(
                ParsedField(
                    path,
                    CandidateValueType.INTEGER,
                    int(match.group(1)),
                    match.group(0),
                    locator,
                    excerpt,
                )
            )
    if not result:
        ranges = {
            (int(match.group(1)), int(match.group(2)))
            for match in re.finditer(
                r"\b(?:between\s+)?(\d{1,3})\s*(?:to|-|and)\s*(\d{1,3})\s*years?\b",
                text,
                re.I,
            )
        }
        if not ranges:
            ranges = {
                (int(match.group(1)), int(match.group(2)))
                for match in re.finditer(
                    r"\bnot\s+(?:be\s+)?less\s+than\s+(\d{1,3})\s+years?.{0,80}?"
                    r"(?:not\s+)?more\s+than\s+(\d{1,3})\s+years?\b",
                    text,
                    re.I,
                )
            }
        if len(ranges) == 1:
            minimum, maximum = next(iter(ranges))
            result.extend(
                (
                    ParsedField(
                        "age.minimum",
                        CandidateValueType.INTEGER,
                        minimum,
                        str(minimum),
                        locator,
                        excerpt,
                    ),
                    ParsedField(
                        "age.maximum",
                        CandidateValueType.INTEGER,
                        maximum,
                        str(maximum),
                        locator,
                        excerpt,
                    ),
                )
            )
    reference = re.search(
        r"(?:(?:reference|cut[ -]?off)\s+date\s*:\s*|as\s+on\s+)"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
        text,
        re.I,
    )
    if reference and (parsed_date := _parse_numeric_date(reference.group(1))):
        result.append(
            ParsedField(
                "age.reference_date",
                CandidateValueType.DATE,
                parsed_date.isoformat(),
                reference.group(1),
                locator,
                excerpt,
            )
        )
    return result


def _application_fee_fields(lines: list[str], locator: str, excerpt: str) -> list[ParsedField]:
    labels = {
        "fee": "application.fee",
        "application fee": "application.fee",
        "exemption": "application.fee_exemptions",
        "exemptions": "application.fee_exemptions",
        "payment mode": "application.payment_mode",
    }
    result: list[ParsedField] = []
    for line in lines:
        match = re.match(r"([^:]{2,40}):\s*(.+)$", line)
        key = re.sub(r"[^a-z]+", " ", match.group(1).casefold()).strip() if match else ""
        if match and key in labels:
            result.extend(_string_field(labels[key], match.group(2), locator, excerpt))
    if not result:
        result.extend(_text_section_field("application.fee", lines, locator, excerpt))
    return result


def _labeled_or_text_fields(
    kind: str, lines: list[str], locator: str, excerpt: str
) -> list[ParsedField]:
    labels = (
        {
            "minimum": "experience.minimum",
            "desirable": "experience.desirable",
            "details": "experience.details",
        }
        if kind == "experience"
        else {
            "pay scale": "pay.scale",
            "grade pay": "pay.grade_pay",
            "pay level": "pay.level",
            "fixed remuneration": "salary.fixed",
            "salary": "salary.details",
        }
    )
    result: list[ParsedField] = []
    for line in lines:
        match = re.match(r"([^:]{2,40}):\s*(.+)$", line)
        key = re.sub(r"[^a-z]+", " ", match.group(1).casefold()).strip() if match else ""
        if match and key in labels:
            result.extend(_string_field(labels[key], match.group(2), locator, excerpt))
    if not result:
        fallback = "experience.minimum" if kind == "experience" else "pay.scale"
        result.extend(_text_section_field(fallback, lines, locator, excerpt))
    return result


def _string_field(path: str, value: str, locator: str, excerpt: str) -> list[ParsedField]:
    cleaned = _clean_text(value)
    return (
        [ParsedField(path, CandidateValueType.STRING, cleaned, value, locator, excerpt)]
        if cleaned
        else []
    )


def _text_section_field(
    path: str, lines: list[str], locator: str, excerpt: str
) -> list[ParsedField]:
    values = _clean_list(lines)
    return _string_field(path, " ".join(values), locator, excerpt) if values else []


def _list_section_field(
    path: str, lines: list[str], locator: str, excerpt: str
) -> list[ParsedField]:
    values = _ordered_items(lines)
    return (
        [ParsedField(path, CandidateValueType.JSON, values, "\n".join(lines), locator, excerpt)]
        if values
        else []
    )


def _ordered_structured_field(
    path: str, lines: list[str], locator: str, excerpt: str
) -> list[ParsedField]:
    table = _section_table(lines)
    if table:
        value: object = table
    else:
        value = [
            {"sequence": index, "name": item}
            for index, item in enumerate(_ordered_items(lines), start=1)
        ]
    return (
        [ParsedField(path, CandidateValueType.JSON, value, "\n".join(lines), locator, excerpt)]
        if value
        else []
    )


def _structured_section_field(
    path: str,
    lines: list[str],
    locator: str,
    excerpt: str,
    *,
    prefer_table: bool = False,
) -> list[ParsedField]:
    table = _section_table(lines) if prefer_table or any("|" in line for line in lines) else []
    if table:
        value: object = table
    else:
        values = _clean_list(lines)
        value = values if len(values) > 1 else (values[0] if values else None)
    if value is None:
        return []
    value_type = CandidateValueType.JSON if isinstance(value, list) else CandidateValueType.STRING
    return [ParsedField(path, value_type, value, "\n".join(lines), locator, excerpt)]


def _section_table(lines: list[str]) -> list[dict[str, str]]:
    table_lines = [line for line in lines if "|" in line]
    if len(table_lines) < 2:
        return []
    headers = _table_cells(table_lines[0])
    if not headers or len(set(_header_key(header) for header in headers)) != len(headers):
        return []
    rows: list[dict[str, str]] = []
    for line in table_lines[1:]:
        cells = _table_cells(line)
        if _separator_row(cells):
            continue
        if len(cells) != len(headers) or not any(cells):
            return []
        rows.append(
            {
                _clean_text(header): _clean_text(cell)
                for header, cell in zip(headers, cells, strict=True)
            }
        )
    return rows


def _clean_list(lines: list[str]) -> list[str]:
    values: list[str] = []
    for line in lines:
        if "|" in line or _separator_row([line]):
            continue
        cleaned = re.sub(r"^\s*(?:[-*\u2022]|\(?\d+[.)]|[a-z][.)])\s*", "", line, flags=re.I)
        cleaned = _clean_text(cleaned)
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def _ordered_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    current: str | None = None
    saw_marker = False
    for line in lines:
        if "|" in line or _separator_row([line]):
            continue
        marker = re.match(
            r"^\s*(?:[-*\u2022]|\(?[ivxlcdm]+[.)]|\(?\d+[.)]|[a-z][.)])\s*(.+)$",
            line,
            re.I,
        )
        if marker:
            if current:
                items.append(_clean_text(current))
            current = marker.group(1)
            saw_marker = True
            continue
        if saw_marker and re.match(r"^\s*\d+(?:\.\d+)+", line):
            break
        if current:
            current = f"{current} {line}"
        elif not saw_marker:
            items.append(_clean_text(line))
    if current:
        items.append(_clean_text(current))
    return list(dict.fromkeys(item for item in items if item))


_NARRATIVE_MARKER = re.compile(r"\b(?P<total>[0-9][0-9,]*)\s+posts?\s+of\s+", re.I)
_NARRATIVE_ORGANISATION = re.compile(
    r"^(?P<name>.+?)\s+(?:in|under)\s+(?P<organisation>.+)$", re.I
)
_NARRATIVE_SEPARATOR = re.compile(r"(?P<separator>,|&|\band\b)\s*$", re.I)


def parse_narrative_vacancies(
    title: str, raw_text: str
) -> tuple[
    tuple[ParsedPost, ...],
    AdvertisementSplitStatus,
    str | None,
    tuple[str, ...],
]:
    """Split bounded vacancy groups, including a shared trailing organization."""
    candidate = ""
    markers: list[re.Match[str]] = []
    for candidate in (_clean_text(title), _clean_text(raw_text[:8000])):
        candidate_markers = list(_NARRATIVE_MARKER.finditer(candidate))
        if len(candidate_markers) >= 2:
            markers = candidate_markers
            break
    if len(markers) < 2:
        return (), AdvertisementSplitStatus.LEGACY_UNSPLIT, None, ()

    grouped: list[tuple[re.Match[str], str, str, str, bool]] = []
    pending: list[tuple[re.Match[str], str]] = []
    group_start = markers[0].start()
    for index, marker in enumerate(markers):
        body_end = markers[index + 1].start() if index + 1 < len(markers) else len(candidate)
        body = candidate[marker.end() : body_end].strip()
        if index + 1 < len(markers):
            separator = _NARRATIVE_SEPARATOR.search(body)
            if separator is None:
                return _ambiguous_narrative()
            body = body[: separator.start()].strip()
            if re.search(r"[.;]", body):
                return _ambiguous_narrative()
        else:
            boundary = re.search(r"[.;]", body)
            if boundary is not None:
                body = body[: boundary.start()].strip()
        if not body or re.search(r"[,;]|\band\b", body, re.I):
            return _ambiguous_narrative()

        qualified = _NARRATIVE_ORGANISATION.match(body)
        if qualified is None:
            pending.append((marker, body.strip(" ,-:")))
            continue
        name = _clean_text(qualified.group("name")).strip(" ,-:")
        organisation = _clean_text(qualified.group("organisation")).strip(" ,-:")
        organisation = re.split(
            r"\s+in\s+the\s+Pay\s+Scale\b", organisation, maxsplit=1, flags=re.I
        )[0].strip()
        if not name or not organisation or re.search(r"[,;]", organisation):
            return _ambiguous_narrative()
        pending.append((marker, name))
        group_excerpt = candidate[group_start:body_end].strip(" ,&")[:8000]
        grouped_qualifier = len(pending) > 1
        grouped.extend(
            (
                pending_marker,
                pending_name,
                organisation,
                group_excerpt,
                grouped_qualifier,
            )
            for pending_marker, pending_name in pending
        )
        pending = []
        if index + 1 < len(markers):
            group_start = markers[index + 1].start()
    if pending or len(grouped) != len(markers):
        return _ambiguous_narrative()

    parsed: list[ParsedPost] = []
    seen_keys: set[str] = set()
    name_counts: dict[str, int] = {}
    for _marker, name, _organisation, _excerpt, _grouped_qualifier in grouped:
        normalized = " ".join(name.casefold().split())
        name_counts[normalized] = name_counts.get(normalized, 0) + 1
    for ordinal, (
        marker,
        base_name,
        organisation,
        excerpt,
        grouped_qualifier,
    ) in enumerate(grouped, start=1):
        normalized_name = " ".join(base_name.casefold().split())
        qualified_base_name = " ".join(
            word.capitalize() if word.islower() else word for word in base_name.split()
        )
        name = (
            f"{qualified_base_name} - {organisation}"
            if grouped_qualifier or name_counts[normalized_name] > 1
            else base_name
        )
        total = int(marker.group("total").replace(",", ""))
        post_key = _stable_post_key(base_name, organisation)
        if total < 1 or post_key in seen_keys:
            note = "Narrative vacancy series contains an invalid total or duplicate Post."
            return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)
        seen_keys.add(post_key)
        locator = f"pdf:narrative-vacancies;item={ordinal}"
        parsed.append(
            ParsedPost(
                post_key=post_key,
                ordinal=ordinal,
                name=name,
                normalized_name=normalized_name,
                source_locator=locator,
                facts=(
                    ParsedField(
                        "name",
                        CandidateValueType.STRING,
                        name,
                        base_name,
                        f"{locator};field=post",
                        excerpt,
                    ),
                    ParsedField(
                        "organisation.name",
                        CandidateValueType.STRING,
                        organisation,
                        organisation,
                        f"{locator};field=organisation",
                        excerpt,
                    ),
                    ParsedField(
                        "vacancies.total",
                        CandidateValueType.INTEGER,
                        total,
                        marker.group("total"),
                        f"{locator};field=total",
                        excerpt,
                    ),
                ),
            )
        )
    posts = tuple(parsed)
    return (
        posts,
        AdvertisementSplitStatus.EXPLICIT,
        f"Deterministically parsed {len(posts)} Posts from an explicit vacancy series.",
        (),
    )


def _ambiguous_narrative() -> tuple[
    tuple[ParsedPost, ...],
    AdvertisementSplitStatus,
    str,
    tuple[str, ...],
]:
    note = "Narrative vacancy series could not be split completely and safely."
    return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)


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
            replace(fact, value=display_name) if fact.field_path == "name" else fact
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
                elif fact_key in _DATE_POST_FACTS:
                    parsed_date = _parse_numeric_date(raw_value)
                    if parsed_date is None:
                        ambiguities.append(
                            f"Post detail {fact_key} at {locator} is not an exact date"
                        )
                        continue
                    value_type = CandidateValueType.DATE
                    value = parsed_date.isoformat()
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


_POST_SCOPE_START = re.compile(
    r"^\s*\d+(?:\.\d+)*(?:\.[A-Z]|\.\d+)?\.?\s+For\s+the\s+posts?\s+of\s+",
    re.I,
)
_POST_SCOPE_END = re.compile(r"^\s*\d+(?:\.\d+)+(?:\.[A-Z]|\.\d+)?\.?\s+", re.I)
_CATEGORY_PATHS = {
    "unreserved": "vacancies.ur",
    "obc/mobc": "vacancies.obc_mobc",
    "tea tribes & adivasi communities": "vacancies.tea_tribes_adivasi",
    "sc": "vacancies.sc",
    "st (p)": "vacancies.st_p",
    "st (h)": "vacancies.st_h",
    "ews": "vacancies.ews",
    "pwbd": "vacancies.pwbd",
    "pwd": "vacancies.pwbd",
    "women": "vacancies.women",
    "ex-servicemen": "vacancies.ex_servicemen",
}
_PRIMARY_CATEGORY_PATHS = {
    "vacancies.ur",
    "vacancies.obc_mobc",
    "vacancies.tea_tribes_adivasi",
    "vacancies.sc",
    "vacancies.st_p",
    "vacancies.st_h",
    "vacancies.ews",
}


def apply_pypdf_post_details(
    raw_text: str, posts: tuple[ParsedPost, ...]
) -> tuple[tuple[ParsedPost, ...], tuple[str, ...]]:
    """Attach Post facts from bounded whitespace/multiline pypdf structures."""
    lines = _source_lines(raw_text)
    fact_maps = [{fact.field_path: fact for fact in post.facts} for post in posts]
    ambiguities: list[str] = []
    for occurrence, block in enumerate(_post_scope_blocks(lines), start=1):
        text = _clean_text(" ".join(block))
        owner_match = re.search(
            r"For\s+the\s+posts?\s+of\s+(.+?)\s*:\s*The\s+age\b", text, re.I
        )
        if owner_match:
            locator = f"pdf:post-scope=age;occurrence={occurrence}"
            matches = _owner_post_indexes(posts, owner_match.group(1))
            age = re.search(
                r"must\s+be\s+(\d{1,3})\s*-\s*(\d{1,3})(?:\s+years?)?\s+as\s+on\s+"
                r"(\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{4})",
                text,
                re.I,
            )
            if not matches or age is None:
                ambiguities.append(f"Post age clause at {locator} has uncertain ownership or shape")
            else:
                parsed_date = _parse_numeric_date(age.group(3))
                if parsed_date is None:
                    ambiguities.append(
                        f"Post age clause at {locator} has an invalid reference date"
                    )
                else:
                    facts = (
                        ParsedField(
                            "age.minimum", CandidateValueType.INTEGER, int(age.group(1)),
                            age.group(1), locator, text[:8000],
                        ),
                        ParsedField(
                            "age.maximum", CandidateValueType.INTEGER, int(age.group(2)),
                            age.group(2), locator, text[:8000],
                        ),
                        ParsedField(
                            "age.reference_date", CandidateValueType.DATE,
                            parsed_date.isoformat(), age.group(3), locator, text[:8000],
                        ),
                    )
                    _attach_post_facts(fact_maps, matches, facts, ambiguities, locator)
        licence_match = re.search(
            r"For\s+the\s+posts?\s+of\s+(.+?),\s*Applicant\s+must\s+possess\s+"
            r"(.+?driving\s+licen[cs]e.+?)(?:\.|$)", text, re.I,
        )
        if licence_match:
            locator = f"pdf:post-scope=licence;occurrence={occurrence}"
            matches = _owner_post_indexes(posts, licence_match.group(1))
            if not matches:
                ambiguities.append(f"Post licence clause at {locator} has uncertain ownership")
            else:
                fact = ParsedField(
                    "qualification.registration_or_licence", CandidateValueType.STRING,
                    _clean_text(licence_match.group(2)), licence_match.group(2), locator,
                    text[:8000],
                )
                _attach_post_facts(fact_maps, matches, (fact,), ambiguities, locator)
    _attach_roster_blocks(lines, posts, fact_maps, ambiguities)
    updated = tuple(
        replace(post, facts=tuple(facts[key] for key in sorted(facts)))
        for post, facts in zip(posts, fact_maps, strict=True)
    )
    return updated, tuple(ambiguities)


def _post_scope_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if _POST_SCOPE_START.match(line):
            if current:
                blocks.append(current)
            current = [line]
        elif current is not None:
            if _POST_SCOPE_END.match(line):
                blocks.append(current)
                current = None
            else:
                current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _canonical_owner(value: str) -> str:
    normalized = _clean_text(value).casefold()
    normalized = re.sub(r"\bf\s*&\s*es\b", "fire emergency services", normalized)
    normalized = re.sub(
        r"\bfire\s*&\s*emergency\s+services\b", "fire emergency services", normalized
    )
    normalized = normalized.replace("handyme n", "handymen")
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _post_organisation(post: ParsedPost) -> str:
    return next(
        (
            str(fact.value)
            for fact in post.facts
            if fact.field_path in {"organisation.name", "department.name"}
        ),
        "",
    )


def _owner_post_indexes(posts: tuple[ParsedPost, ...], owner: str) -> list[int]:
    canonical_owner = _canonical_owner(owner)
    organisations = {
        _canonical_owner(_post_organisation(post)) for post in posts if _post_organisation(post)
    }
    occurrences = sorted(
        (match.start(), match.end(), organisation)
        for organisation in organisations
        for match in re.finditer(rf"\b{re.escape(organisation)}\b", canonical_owner)
    )
    owner_has_post = _owner_mentions_known_post(canonical_owner, posts)
    matches: list[int] = []
    for index, post in enumerate(posts):
        organisation = _canonical_owner(_post_organisation(post))
        base_name = _canonical_owner(post.normalized_name)
        segments = []
        for position, (_start, end, found_organisation) in enumerate(occurrences):
            if found_organisation == organisation:
                previous_end = occurrences[position - 1][1] if position else 0
                segments.append(canonical_owner[previous_end:end])
        name_matches = any(_owner_has_name(segment, base_name) for segment in segments)
        if segments and (name_matches or not owner_has_post):
            matches.append(index)
    return matches


def _owner_mentions_known_post(owner: str, posts: tuple[ParsedPost, ...]) -> bool:
    canonical_owner = _canonical_owner(owner)
    for post in posts:
        base_name = _canonical_owner(post.normalized_name)
        if _owner_has_name(canonical_owner, base_name):
            return True
    return False


def _owner_has_name(owner: str, base_name: str) -> bool:
    if base_name == "driver":
        return bool(re.search(r"\bdriver\b(?!\s+(?:constable|operator))", owner))
    return bool(base_name and base_name in owner)


def _attach_post_facts(
    fact_maps: list[dict[str, ParsedField]], indexes: list[int],
    facts: tuple[ParsedField, ...], ambiguities: list[str], locator: str,
) -> None:
    for index in indexes:
        for fact in facts:
            existing = fact_maps[index].get(fact.field_path)
            if existing is not None and (
                existing.value_type != fact.value_type or existing.value != fact.value
            ):
                ambiguities.append(
                    f"Post fact {fact.field_path} at {locator} conflicts with another value"
                )
                continue
            fact_maps[index][fact.field_path] = fact


def _attach_roster_blocks(
    lines: list[str], posts: tuple[ParsedPost, ...],
    fact_maps: list[dict[str, ParsedField]], ambiguities: list[str],
) -> None:
    heading = re.compile(
        r"^\s*(.+?)\s+in\s+(.+?)\s+with\s+Grade\s+Pay\s+of\s+(Rs\.?\s*[0-9,]+/-?)", re.I
    )
    starts = [(index, match) for index, line in enumerate(lines) if (match := heading.match(line))]
    for occurrence, (start, match) in enumerate(starts, start=1):
        end = (
            starts[occurrence][0]
            if occurrence < len(starts)
            else min(len(lines), start + 80)
        )
        block = lines[start:end]
        total_index = next(
            (
                offset
                for offset, line in enumerate(block)
                if re.match(r"^Total\s+", line, re.I)
            ),
            None,
        )
        if total_index is None:
            continue
        block = block[: total_index + 1]
        owner = f"{match.group(1)} in {match.group(2)}"
        locator = f"pdf:post-roster;occurrence={occurrence}"
        matches = _owner_post_indexes(posts, owner)
        if len(matches) != 1:
            ambiguities.append(f"Post roster at {locator} matches {len(matches)} Posts")
            continue
        post_index = matches[0]
        expected = fact_maps[post_index].get("vacancies.total")
        categories = _category_counts(block)
        reconciled_total = sum(
            value for path, value in categories.items() if path in _PRIMARY_CATEGORY_PATHS
        )
        if expected is None or not categories or reconciled_total != expected.value:
            ambiguities.append(f"Post roster at {locator} does not reconcile to the Post total")
            continue
        excerpt = "\n".join(block)[:8000]
        facts = [
            ParsedField(
                "pay.grade_pay", CandidateValueType.STRING, _clean_text(match.group(3)),
                match.group(3), f"{locator};field=grade-pay", excerpt,
            )
        ]
        for path, value in categories.items():
            facts.append(
                ParsedField(
                    path, CandidateValueType.INTEGER, value, str(value),
                    f"{locator};field={path}", excerpt,
                )
            )
        _attach_post_facts(fact_maps, matches, tuple(facts), ambiguities, locator)


def _category_counts(lines: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    index = 0
    while index < len(lines):
        line = _clean_text(lines[index])
        if re.match(r"^Tea\s+Tribes\s*&\s*Adivasi\s*$", line, re.I) and index + 1 < len(lines):
            line = f"{line} {_clean_text(lines[index + 1])}"
            index += 1
            if not re.search(r"\d", line) and index + 1 < len(lines):
                line = f"{line} {_clean_text(lines[index + 1])}"
                index += 1
        for label, path in _CATEGORY_PATHS.items():
            match = re.match(re.escape(label) + r"\s+(.+)$", line, re.I)
            if match and (numbers := re.findall(r"\b\d+\b", match.group(1))):
                result[path] = int(numbers[-1])
                break
        index += 1
    return result


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
    year = (
        metadata.notification_date.year
        if metadata.notification_date
        else _explicit_year(metadata.title)
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
    match = re.search(
        r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})", value
    )
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
