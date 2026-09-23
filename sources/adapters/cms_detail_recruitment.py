import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
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
class CmsDetailSource(OfficialArchiveSource):
    allowed_hosts: tuple[str, ...] = ()
    detail_path_prefixes: tuple[str, ...] = ()
    max_listing_rows_per_run: int = 100
    max_detail_pages_per_run: int = 10
    allow_undated_detail_links: bool = False


CMS_DETAIL_SOURCE_CANDIDATES = {
    "AGRI_ASSAM": CmsDetailSource(
        source_code="AGRI_ASSAM",
        authority_code="AGRI_ASSAM",
        authority_name="Directorate of Agriculture, Assam",
        authority_type=AuthorityType.DEPARTMENT,
        listing_url="https://diragri.assam.gov.in/resource/recruitment-1",
        adapter_key="cms_detail_agriculture",
        organization_name="Directorate of Agriculture, Assam",
        schedule_group=SourceScheduleGroup.HIGH_PRIORITY,
        poll_interval_minutes=720,
        priority=45,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("diragri.assam.gov.in",),
        detail_path_prefixes=("/node/", "/resource/detail/"),
        max_detail_pages_per_run=10,
    ),
    "NHM_ASSAM": CmsDetailSource(
        source_code="NHM_ASSAM",
        authority_code="NHM_ASSAM",
        authority_name="National Health Mission, Assam",
        authority_type=AuthorityType.AUTONOMOUS_BODY,
        listing_url="https://nhm.assam.gov.in/documents",
        adapter_key="cms_detail_nhm",
        organization_name="National Health Mission, Assam",
        schedule_group=SourceScheduleGroup.HIGH_PRIORITY,
        poll_interval_minutes=720,
        priority=50,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("nhm.assam.gov.in",),
        detail_path_prefixes=("/latest/", "/documents-detail/", "/node/", "/resource/detail/"),
        max_detail_pages_per_run=10,
        allow_undated_detail_links=True,
    ),
    "ASRLM_ASSAM": CmsDetailSource(
        source_code="ASRLM_ASSAM",
        authority_code="ASRLM_ASSAM",
        authority_name="Assam State Rural Livelihoods Mission",
        authority_type=AuthorityType.AUTONOMOUS_BODY,
        listing_url="https://asrlms.assam.gov.in/portlets/recruitment-career",
        adapter_key="cms_detail_asrlm",
        organization_name="Assam State Rural Livelihoods Mission",
        priority=62,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("asrlms.assam.gov.in",),
        detail_path_prefixes=("/latest/", "/resource/", "/node/", "/documents-detail/"),
        max_detail_pages_per_run=10,
        allow_undated_detail_links=True,
    ),
    "SAMAGRA_ASSAM": CmsDetailSource(
        source_code="SAMAGRA_ASSAM",
        authority_code="SAMAGRA_ASSAM",
        authority_name="Samagra Shiksha, Assam",
        authority_type=AuthorityType.AUTONOMOUS_BODY,
        listing_url="https://ssa.assam.gov.in/information-services/detail/recruitment-portal-0",
        adapter_key="cms_detail_samagra",
        organization_name="Samagra Shiksha, Assam",
        schedule_group=SourceScheduleGroup.HIGH_PRIORITY,
        poll_interval_minutes=720,
        priority=48,
        requests_per_minute=4,
        max_notices_per_run=10,
        allowed_hosts=("ssa.assam.gov.in",),
        detail_path_prefixes=(
            "/latest/",
            "/resource/",
            "/node/",
            "/information-services/detail/",
        ),
        max_detail_pages_per_run=10,
        allow_undated_detail_links=True,
    ),
}

# Activation is evidence-driven. A source moves here only after one bounded live validation
# discovers a usable recruitment document with this family.
CMS_DETAIL_SOURCES: dict[str, CmsDetailSource] = {}


@dataclass(frozen=True)
class DetailLink:
    title: str
    url: str
    notification_date: date | None


@dataclass(frozen=True)
class _Anchor:
    href: str
    text: str
    context: str


class _AnchorParser(HTMLParser):
    _CONTAINERS = {"tr", "li", "article"}

    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[_Anchor] = []
        self._href: str | None = None
        self._parts: list[str] = []
        self._container_tag: str | None = None
        self._container_parts: list[str] = []
        self._container_anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in self._CONTAINERS and self._container_tag is None:
            self._container_tag = tag
            self._container_parts = []
            self._container_anchors = []
        if tag == "a":
            self._href = attributes.get("href")
            self._parts = []
        elif tag == "img" and self._href is not None and attributes.get("alt"):
            self._parts.append(attributes["alt"] or "")

    def handle_data(self, data: str) -> None:
        if self._container_tag is not None:
            self._container_parts.append(data)
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = _clean(" ".join(self._parts))
            if self._container_tag is None:
                self.anchors.append(_Anchor(self._href, text, text))
            else:
                self._container_anchors.append((self._href, text))
            self._href = None
            self._parts = []
        if tag == self._container_tag:
            context = _clean(" ".join(self._container_parts))
            self.anchors.extend(
                _Anchor(href, text, context) for href, text in self._container_anchors
            )
            self._container_tag = None
            self._container_parts = []
            self._container_anchors = []


class CmsDetailRecruitmentAdapter:
    """Traverse one bounded official CMS listing to a detail page and one recruitment PDF."""

    def __init__(
        self,
        http: BoundedHttpClient,
        source: CmsDetailSource,
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
        details = parse_cms_detail_listing(
            listing.content,
            self.source,
            cutoff_date=self.cutoff_date,
        )
        warnings: list[str] = []
        notices: list[ArchiveNotice] = []
        if len(details) > self.source.max_listing_rows_per_run:
            warnings.append(
                f"Listing returned {len(details)} recruitment rows; processed bounded first "
                f"{self.source.max_listing_rows_per_run}"
            )
        details = details[: self.source.max_listing_rows_per_run]
        if len(details) > self.source.max_detail_pages_per_run:
            warnings.append(
                f"Listing returned {len(details)} recruitment details; processed bounded first "
                f"{self.source.max_detail_pages_per_run}"
            )
        seen_details: set[str] = set()
        seen_documents: set[str] = set()
        for detail in details[: self.source.max_detail_pages_per_run]:
            if len(notices) >= self.source.max_notices_per_run:
                warnings.append(
                    f"Reached bounded document limit {self.source.max_notices_per_run}"
                )
                break
            try:
                detail_page = self.http.fetch(detail.url, accepted_types=("text/html",))
                if not _is_allowed_url(
                    detail_page.url,
                    self.source,
                    path_prefixes=self.source.detail_path_prefixes,
                ):
                    warnings.append(f"Detail redirect left approved source scope: {detail.url}")
                    continue
                if detail_page.url in seen_details:
                    continue
                seen_details.add(detail_page.url)
                resolved_detail = replace(detail, url=detail_page.url)
                document_url = select_recruitment_document(
                    detail_page.content, resolved_detail, self.source
                )
                if document_url is None:
                    warnings.append(f"No recruitment document found on detail page: {detail.url}")
                    continue
                if document_url in seen_documents:
                    continue
                seen_documents.add(document_url)
                resource = self.http.fetch(document_url, accepted_types=("application/pdf",))
                if not _is_allowed_url(resource.url, self.source):
                    warnings.append(f"Document redirect left approved source scope: {document_url}")
                    continue
                metadata = ArchiveNoticeMetadata(
                    title=detail.title,
                    document_url=resource.url,
                    notification_number=None,
                    notification_date=detail.notification_date,
                )
                extraction = self.extractor(
                    resource.content,
                    metadata,
                    self.source.organization_name,
                )
                metadata = _with_extracted_date(metadata, extraction)
                if notice_before_cutoff(
                    metadata.notification_date, metadata.title, self.cutoff_date
                ):
                    warnings.append(
                        f"Recruitment document outside bounded history window: {document_url}"
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
                    f"Recruitment detail unavailable {detail.url}: {type(error).__name__}: {error}"
                )
        return ArchiveAdapterResult(
            listing_document=AdapterDocument(listing, DocumentType.HTML, "html"),
            notices=tuple(notices),
            warnings=tuple(warnings),
        )


def parse_cms_detail_listing(
    content: bytes,
    source: CmsDetailSource,
    *,
    cutoff_date: date,
) -> list[DetailLink]:
    parser = _AnchorParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    selected: dict[str, DetailLink] = {}
    for anchor in parser.anchors:
        title = _clean(anchor.text)
        context = _clean(anchor.context or title)
        classification_text = context if is_recruitment_advertisement(context) else title
        if not is_recruitment_advertisement(classification_text):
            continue
        if is_recruitment_lifecycle_notice(context):
            continue
        url = urljoin(source.listing_url, anchor.href)
        if not _is_allowed_url(url, source, path_prefixes=source.detail_path_prefixes):
            continue
        notification_date = notice_date_from_title(context)
        if notice_before_cutoff(notification_date, context, cutoff_date):
            continue
        display_title = classification_text
        if title.casefold() not in {
            "details",
            "download",
            "view",
            "read more",
            "click here",
        }:
            display_title = title
        selected[url] = DetailLink(
            _without_trailing_date(display_title),
            url,
            notification_date,
        )
    return sorted(
        selected.values(),
        key=lambda item: (item.notification_date or date.min, item.url),
        reverse=True,
    )


def select_recruitment_document(
    content: bytes,
    detail: DetailLink,
    source: CmsDetailSource,
) -> str | None:
    parser = _AnchorParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    ranked: list[tuple[int, str]] = []
    for anchor in parser.anchors:
        url = urljoin(detail.url, anchor.href)
        if not _is_allowed_url(url, source) or ".pdf" not in urlsplit(url).path.casefold():
            continue
        label = _clean(f"{anchor.text} {anchor.context}")
        if is_recruitment_lifecycle_notice(label):
            continue
        lowered = label.casefold()
        if any(term in lowered for term in ("application form", "terms of reference", "tor")):
            continue
        if is_recruitment_advertisement(label):
            rank = 0
        elif lowered in {"notice", "notification", "recruitment notice", "advertisement"}:
            rank = 1
        elif any(term in url.casefold() for term in ("advertisement", "recruitment", "notice")):
            rank = 2
        else:
            continue
        ranked.append((rank, url))
    if not ranked:
        return None
    return min(ranked)[1]


def _is_allowed_url(
    url: str,
    source: CmsDetailSource,
    *,
    path_prefixes: tuple[str, ...] = (),
) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in source.allowed_hosts:
        return False
    return not path_prefixes or any(parsed.path.startswith(prefix) for prefix in path_prefixes)


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


def _without_trailing_date(title: str) -> str:
    return re.sub(
        r"\s+(?:dated|dtd\.?)\s+\d{1,2}[./-]\d{1,2}[./-]20\d{2}\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
