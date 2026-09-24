import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from app.models.discovery import DocumentType
from app.models.source_registry import AuthorityType, SourceScheduleGroup
from sources.adapters.apsc_recruitment import AdapterDocument
from sources.adapters.official_recruitment_archive import (
    ArchiveAdapterResult,
    ArchiveNotice,
    ArchiveNoticeMetadata,
    OfficialArchiveSource,
    archive_candidate_key,
    is_recruitment_advertisement,
    is_recruitment_lifecycle_notice,
    notice_before_cutoff,
    notice_date_from_title,
    parse_official_advertisement_pdf,
)
from sources.extraction import ParsedAdvertisement
from sources.http import BoundedHttpClient


@dataclass(frozen=True)
class DatedDocumentSource(OfficialArchiveSource):
    allowed_hosts: tuple[str, ...] = ()
    detail_path_prefixes: tuple[str, ...] = ()
    excluded_link_terms: tuple[str, ...] = ()
    max_listing_rows_per_run: int = 100
    max_detail_pages_per_run: int = 10


DATED_DOCUMENT_SOURCE_CANDIDATES = {
    "FREMAA_ASSAM": DatedDocumentSource(
        source_code="FREMAA_ASSAM",
        authority_code="FREMAA_ASSAM",
        authority_name="Flood and River Erosion Management Agency of Assam",
        authority_type=AuthorityType.AUTONOMOUS_BODY,
        listing_url="https://fremaa.assam.gov.in/portlets/recruitment-career",
        adapter_key="dated_document_resolver_fremaa",
        organization_name="Flood and River Erosion Management Agency of Assam",
        priority=64,
        requests_per_minute=4,
        max_notices_per_run=20,
        allowed_hosts=("fremaa.assam.gov.in",),
        detail_path_prefixes=("/latest/", "/resource/", "/documents/"),
    ),
    "ASDM_ASSAM": DatedDocumentSource(
        source_code="ASDM_ASSAM",
        authority_code="ASDM_ASSAM",
        authority_name="Assam Skill Development Mission",
        authority_type=AuthorityType.AUTONOMOUS_BODY,
        listing_url="https://asdm.assam.gov.in/portlets/recruitment-career",
        adapter_key="dated_document_resolver_asdm",
        organization_name="Assam Skill Development Mission",
        priority=56,
        requests_per_minute=4,
        max_notices_per_run=20,
        allowed_hosts=("asdm.assam.gov.in",),
        detail_path_prefixes=("/latest/", "/resource/", "/documents/"),
    ),
    "PNRD_ASSAM": DatedDocumentSource(
        source_code="PNRD_ASSAM",
        authority_code="PNRD_ASSAM",
        authority_name="Panchayat and Rural Development, Assam",
        authority_type=AuthorityType.DEPARTMENT,
        listing_url="https://pnrd.assam.gov.in/documents/recruitment",
        adapter_key="dated_document_resolver_pnrd",
        organization_name="Panchayat and Rural Development, Assam",
        schedule_group=SourceScheduleGroup.HIGH_PRIORITY,
        poll_interval_minutes=720,
        priority=44,
        requests_per_minute=4,
        max_notices_per_run=20,
        allowed_hosts=("pnrd.assam.gov.in",),
        detail_path_prefixes=("/latest/", "/resource/", "/documents/"),
    ),
    "DTE_ASSAM": DatedDocumentSource(
        source_code="DTE_ASSAM",
        authority_code="DTE_ASSAM",
        authority_name="Directorate of Technical Education, Assam",
        authority_type=AuthorityType.DEPARTMENT,
        listing_url="https://dte.assam.gov.in/portlets/recruitment",
        adapter_key="dated_document_resolver_dte",
        organization_name="Directorate of Technical Education, Assam",
        schedule_group=SourceScheduleGroup.HIGH_PRIORITY,
        poll_interval_minutes=720,
        priority=42,
        requests_per_minute=4,
        max_notices_per_run=20,
        allowed_hosts=("dte.assam.gov.in",),
        detail_path_prefixes=("/latest/", "/resource/", "/documents/"),
    ),
}

# Sources move here only after their deterministic tests and bounded live validation succeed.
DATED_DOCUMENT_SOURCES: dict[str, DatedDocumentSource] = {
    code: DATED_DOCUMENT_SOURCE_CANDIDATES[code]
    for code in ("FREMAA_ASSAM", "DTE_ASSAM")
}


@dataclass(frozen=True)
class DocumentListingItem:
    title: str
    url: str
    notification_date: date | None
    direct_document: bool


@dataclass(frozen=True)
class _Anchor:
    href: str
    text: str
    context: str


class _ListingParser(HTMLParser):
    _CONTAINERS = {"tr", "li", "article"}

    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[_Anchor] = []
        self._container_tag: str | None = None
        self._container_parts: list[str] = []
        self._container_anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in self._CONTAINERS and self._container_tag is None:
            self._container_tag = tag
            self._container_parts = []
            self._container_anchors = []
        if tag == "a":
            self._href = attributes.get("href")
            self._anchor_parts = []
        elif tag == "img" and self._href and attributes.get("alt"):
            self._anchor_parts.append(attributes["alt"] or "")

    def handle_data(self, data: str) -> None:
        if self._container_tag is not None:
            self._container_parts.append(data)
        if self._href is not None:
            self._anchor_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = _clean(" ".join(self._anchor_parts))
            if self._container_tag is None:
                self.anchors.append(_Anchor(self._href, text, text))
            else:
                self._container_anchors.append((self._href, text))
            self._href = None
            self._anchor_parts = []
        if tag == self._container_tag:
            context = _clean(" ".join(self._container_parts))
            self.anchors.extend(
                _Anchor(href, text, context) for href, text in self._container_anchors
            )
            self._container_tag = None
            self._container_parts = []
            self._container_anchors = []


class DatedDocumentResolverAdapter:
    """Resolve a bounded mixed official listing into recruitment documents."""

    def __init__(
        self,
        http: BoundedHttpClient,
        source: DatedDocumentSource,
        *,
        cutoff_date: date,
        extractor: Callable[[bytes, ArchiveNoticeMetadata, str], ParsedAdvertisement] | None = None,
    ) -> None:
        self.http = http
        self.source = source
        self.cutoff_date = cutoff_date
        self.extractor = extractor or parse_official_advertisement_pdf

    def discover(self) -> ArchiveAdapterResult:
        listing = self.http.fetch(self.source.listing_url, accepted_types=("text/html",))
        items = parse_dated_document_listing(
            listing.content,
            self.source,
            cutoff_date=self.cutoff_date,
        )
        warnings: list[str] = []
        notices: list[ArchiveNotice] = []
        if len(items) > self.source.max_listing_rows_per_run:
            warnings.append(
                f"Listing returned {len(items)} recruitment rows; processed bounded first "
                f"{self.source.max_listing_rows_per_run}"
            )
        detail_pages = 0
        fetched_documents: set[str] = set()
        for item in items[: self.source.max_listing_rows_per_run]:
            if len(notices) >= self.source.max_notices_per_run:
                warnings.append(
                    f"Reached bounded document limit {self.source.max_notices_per_run}"
                )
                break
            try:
                document_url = item.url
                if not item.direct_document:
                    if detail_pages >= self.source.max_detail_pages_per_run:
                        warnings.append(
                            f"Reached bounded detail-page limit "
                            f"{self.source.max_detail_pages_per_run}"
                        )
                        break
                    detail_pages += 1
                    detail = self.http.fetch(item.url, accepted_types=("text/html",))
                    if not _is_allowed_url(detail.url, self.source, require_detail_path=True):
                        warnings.append(f"Detail redirect left approved source scope: {item.url}")
                        continue
                    document_url = resolve_document_from_detail(
                        detail.content,
                        replace(item, url=detail.url),
                        self.source,
                    )
                    if document_url is None:
                        warnings.append(f"No recruitment document found: {item.url}")
                        continue
                if document_url in fetched_documents:
                    continue
                fetched_documents.add(document_url)
                resource = self.http.fetch(document_url, accepted_types=("application/pdf",))
                if not _is_allowed_url(resource.url, self.source):
                    warnings.append(f"Document redirect left approved source scope: {document_url}")
                    continue
                metadata = ArchiveNoticeMetadata(
                    title=item.title,
                    document_url=resource.url,
                    notification_number=None,
                    notification_date=item.notification_date,
                )
                extraction = self.extractor(
                    resource.content,
                    metadata,
                    self.source.organization_name,
                )
                metadata = _with_extracted_date(metadata, extraction)
                if notice_before_cutoff(
                    metadata.notification_date,
                    metadata.title,
                    self.cutoff_date,
                ):
                    warnings.append(
                        f"Recruitment document outside bounded history window: {resource.url}"
                    )
                    continue
                warnings.extend(extraction.warnings)
                notices.append(
                    ArchiveNotice(
                        metadata=metadata,
                        document=AdapterDocument(resource, DocumentType.PDF, "pdf"),
                        candidate_key=archive_candidate_key(self.source.authority_code, metadata),
                        fields=extraction.fields,
                        posts=extraction.posts,
                        split_status=extraction.split_status,
                        split_note=extraction.split_note,
                    )
                )
            except Exception as error:
                warnings.append(
                    f"Recruitment item unavailable {item.url}: "
                    f"{type(error).__name__}: {error}"
                )
        return ArchiveAdapterResult(
            listing_document=AdapterDocument(listing, DocumentType.HTML, "html"),
            notices=tuple(notices),
            warnings=tuple(warnings),
        )


def parse_dated_document_listing(
    content: bytes,
    source: DatedDocumentSource,
    *,
    cutoff_date: date,
) -> list[DocumentListingItem]:
    parser = _ListingParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    selected: dict[str, DocumentListingItem] = {}
    for anchor in parser.anchors:
        context = _clean(anchor.context or anchor.text)
        title = _clean(anchor.text)
        link_identity = f"{title} {anchor.href}".casefold()
        if any(term.casefold() in link_identity for term in source.excluded_link_terms):
            continue
        classification_text = context if is_recruitment_advertisement(context) else title
        if not is_recruitment_advertisement(classification_text):
            continue
        if is_recruitment_lifecycle_notice(context):
            continue
        url = urljoin(source.listing_url, anchor.href)
        if not _is_allowed_url(url, source):
            continue
        direct_document = _is_pdf_url(url)
        if not direct_document and not _is_allowed_url(
            url,
            source,
            require_detail_path=True,
        ):
            continue
        notification_date = _listing_date(context) or notice_date_from_title(context)
        if notice_before_cutoff(notification_date, context, cutoff_date):
            continue
        display_title = classification_text
        if title.casefold() not in {"download", "view", "details", "click here"}:
            display_title = title
        selected[url] = DocumentListingItem(
            title=_clean(display_title),
            url=url,
            notification_date=notification_date,
            direct_document=direct_document,
        )
    return sorted(
        selected.values(),
        key=lambda item: (item.notification_date or date.min, item.url),
        reverse=True,
    )


def resolve_document_from_detail(
    content: bytes,
    item: DocumentListingItem,
    source: DatedDocumentSource,
) -> str | None:
    parser = _ListingParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    ranked: list[tuple[int, str]] = []
    for anchor in parser.anchors:
        url = urljoin(item.url, anchor.href)
        if not _is_pdf_url(url) or not _is_allowed_url(url, source):
            continue
        label = _clean(f"{anchor.text} {anchor.context}")
        if is_recruitment_lifecycle_notice(label):
            continue
        lowered = label.casefold()
        if any(term in lowered for term in ("application form", "terms of reference", "tor")):
            continue
        rank = 0 if is_recruitment_advertisement(label) else 1
        if rank == 1 and not any(
            term in lowered for term in ("advertisement", "recruitment", "vacancy", "notice")
        ):
            continue
        ranked.append((rank, url))
    return min(ranked)[1] if ranked else None


def _is_allowed_url(
    url: str,
    source: DatedDocumentSource,
    *,
    require_detail_path: bool = False,
) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in source.allowed_hosts:
        return False
    if not require_detail_path:
        return True
    return any(parsed.path.startswith(prefix) for prefix in source.detail_path_prefixes)


def _is_pdf_url(url: str) -> bool:
    return urlsplit(url).path.casefold().endswith(".pdf")


def _listing_date(value: str) -> date | None:
    numeric = re.search(r"\b(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(20\d{2})\b", value)
    if numeric:
        try:
            return date(int(numeric.group(3)), int(numeric.group(2)), int(numeric.group(1)))
        except ValueError:
            return None
    iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", value)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    named = re.search(
        r"\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+(20\d{2})\b",
        value,
        re.IGNORECASE,
    )
    if named:
        try:
            return datetime.strptime(" ".join(named.groups()), "%d %B %Y").date()
        except ValueError:
            try:
                return datetime.strptime(" ".join(named.groups()), "%d %b %Y").date()
            except ValueError:
                return None
    return None


def _with_extracted_date(
    metadata: ArchiveNoticeMetadata,
    extraction: ParsedAdvertisement,
) -> ArchiveNoticeMetadata:
    if metadata.notification_date is not None:
        return metadata
    field = next(
        (field for field in extraction.fields if field.field_path == "notification.date"),
        None,
    )
    if field is None or not isinstance(field.value, str):
        return metadata
    try:
        return replace(metadata, notification_date=date.fromisoformat(field.value))
    except ValueError:
        return metadata


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
