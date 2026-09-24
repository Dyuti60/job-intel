import logging
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urljoin

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.models.candidates import AdvertisementSplitStatus, CandidateValueType, RecruitmentCandidate
from app.services.official_archive_discovery import OfficialArchiveDiscoveryWorkerService
from app.services.pipeline_orchestrator import PIPELINE_SOURCES
from app.services.source_scheduler import source_schedule_catalog
from sources.adapters.custom_html_recruitment import (
    CUSTOM_HTML_SOURCE_CANDIDATES,
    CUSTOM_HTML_SOURCES,
    CustomHtmlListingAdapter,
)
from sources.adapters.dated_document_resolver import (
    parse_dated_document_listing,
)
from sources.adapters.official_recruitment_archive import archive_candidate_key
from sources.extraction import ParsedAdvertisement, ParsedField
from sources.http import FetchedResource
from sources.post_structure import structure_posts

CASES = (
    (
        "APDCL_ASSAM",
        "apdcl_listing.html",
        "apdcl_detail.html",
        "/website/Career/assistant-manager",
        "https://apdcl.org/career/field-assistant",
    ),
    (
        "APGCL_ASSAM",
        "apgcl_listing.html",
        "apgcl_detail.html",
        "/public/en/career/recruitments/assistant-manager",
        "https://apgcl.org/career/field-assistant",
    ),
    (
        "AEGCL_ASSAM",
        "aegcl_listing.html",
        "aegcl_detail.html",
        "/career-recruitment/assistant-manager",
        "https://aegcl.co.in/career/field-assistant",
    ),
    (
        "GAUHATI_UNIVERSITY",
        "gauhati_university_listing.html",
        "gauhati_university_detail.html",
        "/recruitment/research-assistant",
        "https://gauhati.ac.in/notifications/project-assistant",
    ),
    (
        "DIBRUGARH_UNIVERSITY",
        "dibrugarh_university_listing.html",
        "dibrugarh_university_detail.html",
        "/categories/archive/recruitment-notices/2026/September/research-assistant",
        "https://dibru.ac.in/notifications/project-assistant",
    ),
    (
        "COTTON_UNIVERSITY",
        "cotton_university_listing.html",
        "cotton_university_detail.html",
        "https://www.cottonuniversity.ac.in/recruitment/research-assistant",
        "https://www.cottonuniversity.ac.in/advertisement/project-assistant",
    ),
    (
        "ASTU_ASSAM",
        "astu_listing.html",
        "astu_detail.html",
        "/recruitment/research-assistant",
        "https://www.astu.ac.in/career/project-assistant",
    ),
)


def _fixture(name: str) -> bytes:
    return (Path(__file__).parent / "fixtures" / "power_html" / name).read_bytes()


def _resource(url: str, content: bytes, content_type: str) -> FetchedResource:
    return FetchedResource(
        url=url,
        content=content,
        status_code=200,
        content_type=content_type,
        etag='"fixture"',
        last_modified=None,
        retrieved_at=datetime(2026, 9, 24, tzinfo=UTC),
    )


class _FakeHttp:
    def __init__(self, resources: dict[str, FetchedResource]) -> None:
        self.resources = resources
        self.calls: list[str] = []

    def fetch(self, url: str, *, accepted_types: tuple[str, ...]) -> FetchedResource:
        self.calls.append(url)
        resource = self.resources[url]
        assert (resource.content_type or "").split(";", 1)[0] in accepted_types
        return resource


def _extract_fixture(content: bytes, metadata, organization_name) -> ParsedAdvertisement:
    assert content == b"%PDF fixture"
    posts, split_status, split_note, warnings = structure_posts(metadata.title, "")
    return ParsedAdvertisement(
        fields=(
            ParsedField(
                "organization.name",
                CandidateValueType.STRING,
                organization_name,
                organization_name,
                "pdf:page=1",
                organization_name,
            ),
        ),
        posts=posts,
        split_status=split_status,
        split_note=split_note,
        warnings=warnings,
    )


def test_only_live_validated_power_sources_are_registered() -> None:
    assert set(CUSTOM_HTML_SOURCES) == {"APGCL_ASSAM", "AEGCL_ASSAM"}
    assert set(CUSTOM_HTML_SOURCES) <= set(PIPELINE_SOURCES)
    assert set(CUSTOM_HTML_SOURCES) <= set(source_schedule_catalog())
    assert "APDCL_ASSAM" not in PIPELINE_SOURCES
    assert {source.priority for source in CUSTOM_HTML_SOURCE_CANDIDATES.values()} == {
        66,
        67,
        68,
        74,
        75,
        76,
        78,
    }


@pytest.mark.parametrize(
    ("source_code", "listing_fixture", "detail_fixture", "dated_path", "undated_url"),
    CASES,
)
def test_power_listing_filters_lifecycle_dates_and_unsafe_hosts(
    source_code: str,
    listing_fixture: str,
    detail_fixture: str,
    dated_path: str,
    undated_url: str,
) -> None:
    source = CUSTOM_HTML_SOURCE_CANDIDATES[source_code]

    items = parse_dated_document_listing(
        _fixture(listing_fixture),
        source,
        cutoff_date=date(2025, 9, 24),
    )

    assert len(items) == 2
    assert items[0].url == urljoin(source.listing_url, dated_path)
    assert items[0].notification_date == date(2026, 9, 1)
    assert items[1].url == undated_url
    assert items[1].notification_date is None
    assert all("example.invalid" not in item.url for item in items)


@pytest.mark.parametrize(
    ("source_code", "listing_fixture", "detail_fixture", "dated_path", "undated_url"),
    CASES,
)
def test_power_source_resolves_document_and_shared_post_structure(
    source_code: str,
    listing_fixture: str,
    detail_fixture: str,
    dated_path: str,
    undated_url: str,
) -> None:
    source = replace(
        CUSTOM_HTML_SOURCE_CANDIDATES[source_code],
        max_listing_rows_per_run=1,
        max_detail_pages_per_run=1,
        max_notices_per_run=1,
    )
    detail_url = urljoin(source.listing_url, dated_path)
    document_url = urljoin(source.listing_url, "/docs/recruitment-advertisement.pdf")
    http = _FakeHttp(
        {
            source.listing_url: _resource(
                source.listing_url,
                _fixture(listing_fixture),
                "text/html",
            ),
            detail_url: _resource(
                detail_url,
                _fixture(detail_fixture),
                "text/html",
            ),
            document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = CustomHtmlListingAdapter(
        http,
        source,
        cutoff_date=date(2025, 9, 24),
        extractor=_extract_fixture,
    ).discover()

    assert http.calls == [source.listing_url, detail_url, document_url]
    assert len(result.notices) == 1
    notice = result.notices[0]
    assert notice.candidate_key == archive_candidate_key(source.authority_code, notice.metadata)
    assert notice.split_status == AdvertisementSplitStatus.EXPLICIT
    assert len(notice.posts) == 1


@pytest.mark.parametrize(
    ("source_code", "listing_fixture", "detail_fixture", "dated_path", "undated_url"),
    CASES,
)
def test_power_source_skips_malformed_detail_safely(
    source_code: str,
    listing_fixture: str,
    detail_fixture: str,
    dated_path: str,
    undated_url: str,
) -> None:
    source = replace(
        CUSTOM_HTML_SOURCE_CANDIDATES[source_code],
        max_listing_rows_per_run=1,
        max_detail_pages_per_run=1,
    )
    detail_url = urljoin(source.listing_url, dated_path)
    http = _FakeHttp(
        {
            source.listing_url: _resource(
                source.listing_url,
                _fixture(listing_fixture),
                "text/html",
            ),
            detail_url: _resource(
                detail_url,
                b'<a href="/docs/application-form.pdf">Application Form</a>',
                "text/html",
            ),
        }
    )

    result = CustomHtmlListingAdapter(
        http,
        source,
        cutoff_date=date(2025, 9, 24),
        extractor=_extract_fixture,
    ).discover()

    assert result.notices == ()
    assert any("No recruitment document" in warning for warning in result.warnings)


def test_power_family_bounds_rows_documents_deduplicates_and_does_not_recurse() -> None:
    source = replace(
        CUSTOM_HTML_SOURCE_CANDIDATES["APGCL_ASSAM"],
        max_listing_rows_per_run=2,
        max_detail_pages_per_run=2,
        max_notices_per_run=1,
    )
    listing = b"""
    <a href="/public/en/career/one">Advertisement for 3 posts dated 03/09/2026</a>
    <a href="/public/en/career/one">Advertisement for 3 posts dated 03/09/2026</a>
    <a href="/public/en/career/two">Advertisement for 2 posts dated 02/09/2026</a>
    <a href="/public/en/career/three">Advertisement for 1 post dated 01/09/2026</a>
    """
    first_detail = urljoin(source.listing_url, "/public/en/career/one")
    document_url = urljoin(source.listing_url, "/docs/recruitment.pdf")
    detail = b"""
    <a href="/public/en/career/recursive">Recruitment detail</a>
    <a href="/docs/recruitment.pdf">Advertisement</a>
    """
    http = _FakeHttp(
        {
            source.listing_url: _resource(source.listing_url, listing, "text/html"),
            first_detail: _resource(first_detail, detail, "text/html"),
            document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = CustomHtmlListingAdapter(
        http,
        source,
        cutoff_date=date(2025, 9, 24),
        extractor=_extract_fixture,
    ).discover()

    assert len(result.notices) == 1
    assert len(parse_dated_document_listing(listing, source, cutoff_date=date(2025, 9, 24))) == 3
    assert http.calls == [source.listing_url, first_detail, document_url]
    assert any("bounded first 2" in warning for warning in result.warnings)
    assert any("document limit 1" in warning for warning in result.warnings)
    assert not any("recursive" in call for call in http.calls)


@pytest.mark.parametrize(
    ("source_code", "listing_fixture", "detail_fixture", "dated_path", "undated_url"),
    CASES,
)
def test_power_source_rediscovery_is_idempotent(
    db_session,
    tmp_path,
    source_code: str,
    listing_fixture: str,
    detail_fixture: str,
    dated_path: str,
    undated_url: str,
) -> None:
    source = replace(
        CUSTOM_HTML_SOURCE_CANDIDATES[source_code],
        max_listing_rows_per_run=1,
        max_detail_pages_per_run=1,
        max_notices_per_run=1,
    )
    detail_url = urljoin(source.listing_url, dated_path)
    document_url = urljoin(source.listing_url, "/docs/recruitment-advertisement.pdf")

    def adapter() -> CustomHtmlListingAdapter:
        return CustomHtmlListingAdapter(
            _FakeHttp(
                {
                    source.listing_url: _resource(
                        source.listing_url,
                        _fixture(listing_fixture),
                        "text/html",
                    ),
                    detail_url: _resource(
                        detail_url,
                        _fixture(detail_fixture),
                        "text/html",
                    ),
                    document_url: _resource(
                        document_url,
                        b"%PDF fixture",
                        "application/pdf",
                    ),
                }
            ),
            source,
            cutoff_date=date(2025, 9, 24),
            extractor=_extract_fixture,
        )

    worker = OfficialArchiveDiscoveryWorkerService(
        db_session,
        Settings(raw_storage_root=str(tmp_path)),
        logging.getLogger(__name__),
        source,
    )
    first = worker.run(adapter=adapter())
    second = worker.run(adapter=adapter())

    assert (first.candidates_created, second.candidates_reused) == (1, 1)
    assert (first.revisions_created, second.revisions_reused) == (1, 1)
    assert db_session.scalar(select(func.count()).select_from(RecruitmentCandidate)) == 1
