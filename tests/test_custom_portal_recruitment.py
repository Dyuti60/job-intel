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
from sources.adapters.custom_portal_recruitment import (
    CUSTOM_PORTAL_SOURCE_CANDIDATES,
    CUSTOM_PORTAL_SOURCES,
    CustomPortalAdapter,
)
from sources.adapters.dated_document_resolver import parse_dated_document_listing
from sources.adapters.official_recruitment_archive import archive_candidate_key
from sources.extraction import ParsedAdvertisement, ParsedField
from sources.http import FetchedResource
from sources.post_structure import structure_posts

CASES = (
    (
        "AMTRON_ASSAM",
        "amtron_listing.html",
        "amtron_detail.html",
        "/recruitment/assistant-manager",
        "https://recruitment.amtron.in/advertisement/field-assistant",
        "https://recruitment.amtron.in/documents/recruitment-advertisement.pdf",
    ),
    (
        "AAU_ASSAM",
        "aau_listing.html",
        "aau_detail.html",
        "/recuitments/details.php?id=1",
        "https://www.appl.aau.ac.in/recuitments/details.php?id=2",
        "https://www.aau.ac.in/documents/recruitment-advertisement.pdf",
    ),
)


def _fixture(name: str) -> bytes:
    return (Path(__file__).parent / "fixtures" / "portal_html" / name).read_bytes()


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


def test_portal_candidates_remain_unregistered_until_live_validation() -> None:
    assert CUSTOM_PORTAL_SOURCES == {}
    assert set(CUSTOM_PORTAL_SOURCE_CANDIDATES) == {"AMTRON_ASSAM", "AAU_ASSAM"}
    assert not set(CUSTOM_PORTAL_SOURCE_CANDIDATES) & set(PIPELINE_SOURCES)
    assert not set(CUSTOM_PORTAL_SOURCE_CANDIDATES) & set(source_schedule_catalog())


@pytest.mark.parametrize(
    (
        "source_code",
        "listing_fixture",
        "detail_fixture",
        "dated_path",
        "undated_url",
        "document_url",
    ),
    CASES,
)
def test_portal_listing_filters_actions_lifecycle_dates_and_unsafe_hosts(
    source_code: str,
    listing_fixture: str,
    detail_fixture: str,
    dated_path: str,
    undated_url: str,
    document_url: str,
) -> None:
    source = CUSTOM_PORTAL_SOURCE_CANDIDATES[source_code]

    items = parse_dated_document_listing(
        _fixture(listing_fixture), source, cutoff_date=date(2025, 9, 24)
    )

    assert [(item.url, item.notification_date) for item in items] == [
        (urljoin(source.listing_url, dated_path), date(2026, 9, 1)),
        (undated_url, None),
    ]
    assert all("apply" not in item.url and "login" not in item.url for item in items)


@pytest.mark.parametrize(
    (
        "source_code",
        "listing_fixture",
        "detail_fixture",
        "dated_path",
        "undated_url",
        "document_url",
    ),
    CASES,
)
def test_portal_resolves_official_document_and_shared_post_structure(
    source_code: str,
    listing_fixture: str,
    detail_fixture: str,
    dated_path: str,
    undated_url: str,
    document_url: str,
) -> None:
    source = replace(
        CUSTOM_PORTAL_SOURCE_CANDIDATES[source_code],
        max_listing_rows_per_run=1,
        max_detail_pages_per_run=1,
        max_notices_per_run=1,
    )
    detail_url = urljoin(source.listing_url, dated_path)
    http = _FakeHttp(
        {
            source.listing_url: _resource(
                source.listing_url, _fixture(listing_fixture), "text/html"
            ),
            detail_url: _resource(detail_url, _fixture(detail_fixture), "text/html"),
            document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = CustomPortalAdapter(
        http, source, cutoff_date=date(2025, 9, 24), extractor=_extract_fixture
    ).discover()

    assert http.calls == [source.listing_url, detail_url, document_url]
    assert len(result.notices) == 1
    notice = result.notices[0]
    assert notice.candidate_key == archive_candidate_key(source.authority_code, notice.metadata)
    assert notice.split_status == AdvertisementSplitStatus.EXPLICIT
    assert len(notice.posts) == 1


@pytest.mark.parametrize(
    (
        "source_code",
        "listing_fixture",
        "detail_fixture",
        "dated_path",
        "undated_url",
        "document_url",
    ),
    CASES,
)
def test_portal_skips_unsupported_detail_safely(
    source_code: str,
    listing_fixture: str,
    detail_fixture: str,
    dated_path: str,
    undated_url: str,
    document_url: str,
) -> None:
    source = replace(
        CUSTOM_PORTAL_SOURCE_CANDIDATES[source_code],
        max_listing_rows_per_run=1,
        max_detail_pages_per_run=1,
    )
    detail_url = urljoin(source.listing_url, dated_path)
    http = _FakeHttp(
        {
            source.listing_url: _resource(
                source.listing_url, _fixture(listing_fixture), "text/html"
            ),
            detail_url: _resource(
                detail_url,
                b'<a href="/documents/application-form.pdf">Application form</a>',
                "text/html",
            ),
        }
    )

    result = CustomPortalAdapter(
        http, source, cutoff_date=date(2025, 9, 24), extractor=_extract_fixture
    ).discover()

    assert result.notices == ()
    assert any("No recruitment document" in warning for warning in result.warnings)


def test_portal_family_bounds_deduplicates_and_does_not_recurse() -> None:
    source = replace(
        CUSTOM_PORTAL_SOURCE_CANDIDATES["AMTRON_ASSAM"],
        max_listing_rows_per_run=2,
        max_detail_pages_per_run=2,
        max_notices_per_run=1,
    )
    listing = b"""
    <a href="/recruitment/one">Advertisement for 3 posts dated 03/09/2026</a>
    <a href="/recruitment/one">Advertisement for 3 posts dated 03/09/2026</a>
    <a href="/recruitment/two">Advertisement for 2 posts dated 02/09/2026</a>
    <a href="/recruitment/three">Advertisement for 1 post dated 01/09/2026</a>
    """
    detail_url = urljoin(source.listing_url, "/recruitment/one")
    document_url = urljoin(source.listing_url, "/documents/recruitment.pdf")
    detail = b"""
    <a href="/recruitment/recursive">Recruitment detail</a>
    <a href="/documents/recruitment.pdf">Advertisement</a>
    """
    http = _FakeHttp(
        {
            source.listing_url: _resource(source.listing_url, listing, "text/html"),
            detail_url: _resource(detail_url, detail, "text/html"),
            document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = CustomPortalAdapter(
        http, source, cutoff_date=date(2025, 9, 24), extractor=_extract_fixture
    ).discover()

    assert len(result.notices) == 1
    assert http.calls == [source.listing_url, detail_url, document_url]
    assert any("bounded first 2" in warning for warning in result.warnings)
    assert any("document limit 1" in warning for warning in result.warnings)
    assert not any("recursive" in call for call in http.calls)


@pytest.mark.parametrize(
    (
        "source_code",
        "listing_fixture",
        "detail_fixture",
        "dated_path",
        "undated_url",
        "document_url",
    ),
    CASES,
)
def test_portal_rediscovery_is_idempotent(
    db_session,
    tmp_path,
    source_code: str,
    listing_fixture: str,
    detail_fixture: str,
    dated_path: str,
    undated_url: str,
    document_url: str,
) -> None:
    source = replace(
        CUSTOM_PORTAL_SOURCE_CANDIDATES[source_code],
        max_listing_rows_per_run=1,
        max_detail_pages_per_run=1,
        max_notices_per_run=1,
    )
    detail_url = urljoin(source.listing_url, dated_path)

    def adapter() -> CustomPortalAdapter:
        return CustomPortalAdapter(
            _FakeHttp(
                {
                    source.listing_url: _resource(
                        source.listing_url, _fixture(listing_fixture), "text/html"
                    ),
                    detail_url: _resource(detail_url, _fixture(detail_fixture), "text/html"),
                    document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
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
