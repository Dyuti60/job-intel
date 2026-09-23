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
from sources.adapters.dated_document_resolver import (
    DATED_DOCUMENT_SOURCE_CANDIDATES,
    DATED_DOCUMENT_SOURCES,
    DatedDocumentResolverAdapter,
    parse_dated_document_listing,
)
from sources.adapters.official_recruitment_archive import archive_candidate_key
from sources.extraction import ParsedAdvertisement, ParsedField
from sources.http import FetchedResource
from sources.post_structure import structure_posts

CASES = (
    ("FREMAA_ASSAM", "fremaa.html", "/latest/finance-assistant"),
    ("ASDM_ASSAM", "asdm.html", "/resource/recruitment/project-coordinator"),
    ("PNRD_ASSAM", "pnrd.html", "/documents/recruitment/rural-development-assistant"),
    ("DTE_ASSAM", "dte.html", "/latest/recruitment-of-senior-instructor"),
)


def test_only_live_validated_batch_sources_are_registered() -> None:
    assert set(DATED_DOCUMENT_SOURCES) == {"FREMAA_ASSAM", "DTE_ASSAM"}
    assert set(DATED_DOCUMENT_SOURCES) <= set(PIPELINE_SOURCES)
    assert set(DATED_DOCUMENT_SOURCES) <= set(source_schedule_catalog())
    assert "ASDM_ASSAM" not in PIPELINE_SOURCES
    assert "PNRD_ASSAM" not in PIPELINE_SOURCES


def _fixture(name: str) -> bytes:
    return (Path(__file__).parent / "fixtures" / "dated_document" / name).read_bytes()


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


@pytest.mark.parametrize(("source_code", "fixture_name", "detail_path"), CASES)
def test_each_source_listing_filters_dates_lifecycle_and_unsafe_rows(
    source_code: str,
    fixture_name: str,
    detail_path: str,
) -> None:
    source = DATED_DOCUMENT_SOURCE_CANDIDATES[source_code]

    items = parse_dated_document_listing(
        _fixture(fixture_name),
        source,
        cutoff_date=date(2025, 9, 24),
    )

    assert len(items) == 2
    assert items[0].notification_date == date(2026, 9, 1)
    assert items[0].direct_document is True
    assert items[1].url == urljoin(source.listing_url, detail_path)
    assert items[1].notification_date is None
    assert items[1].direct_document is False
    assert all("old" not in item.url for item in items)
    assert all("example.invalid" not in item.url for item in items)


@pytest.mark.parametrize(("source_code", "fixture_name", "detail_path"), CASES)
def test_each_source_resolves_document_and_hands_off_to_shared_post_structuring(
    source_code: str,
    fixture_name: str,
    detail_path: str,
) -> None:
    source = DATED_DOCUMENT_SOURCE_CANDIDATES[source_code]
    listing = _fixture(fixture_name)
    direct_url = urljoin(source.listing_url, "/sites/default/files/advertisement-current.pdf")
    detail_url = urljoin(source.listing_url, detail_path)
    detail_document_url = urljoin(
        source.listing_url,
        "/sites/default/files/undated-advertisement.pdf",
    )
    detail = b'<a href="/sites/default/files/undated-advertisement.pdf">Advertisement</a>'
    http = _FakeHttp(
        {
            source.listing_url: _resource(source.listing_url, listing, "text/html"),
            direct_url: _resource(direct_url, b"%PDF fixture", "application/pdf"),
            detail_url: _resource(detail_url, detail, "text/html"),
            detail_document_url: _resource(
                detail_document_url,
                b"%PDF fixture",
                "application/pdf",
            ),
        }
    )

    result = DatedDocumentResolverAdapter(
        http,
        source,
        cutoff_date=date(2025, 9, 24),
        extractor=_extract_fixture,
    ).discover()

    assert len(result.notices) == 2
    assert result.notices[0].split_status in set(AdvertisementSplitStatus)
    if result.notices[0].split_status == AdvertisementSplitStatus.EXPLICIT:
        assert result.notices[0].posts
    assert result.notices[1].metadata.notification_date is None
    assert result.notices[0].candidate_key == archive_candidate_key(
        source.authority_code,
        result.notices[0].metadata,
    )
    assert direct_url in http.calls
    assert detail_document_url in http.calls


def test_shared_resolver_bounds_rows_documents_and_suppresses_duplicate_links() -> None:
    source = replace(
        DATED_DOCUMENT_SOURCE_CANDIDATES["FREMAA_ASSAM"],
        max_listing_rows_per_run=2,
        max_notices_per_run=1,
    )
    html = b"""
    <ul>
      <li>03-09-2026 <a href="/files/three.pdf">Advertisement for 3 posts</a></li>
      <li>02-09-2026 <a href="/files/two.pdf">Advertisement for 2 posts</a></li>
      <li>02-09-2026 <a href="/files/two.pdf">Advertisement for 2 posts</a></li>
      <li>01-09-2026 <a href="/files/one.pdf">Advertisement for 1 post</a></li>
      <li><a href="https://example.invalid/outside.pdf">Advertisement outside</a></li>
    </ul>
    """
    first_url = urljoin(source.listing_url, "/files/three.pdf")
    http = _FakeHttp(
        {
            source.listing_url: _resource(source.listing_url, html, "text/html"),
            first_url: _resource(first_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = DatedDocumentResolverAdapter(
        http,
        source,
        cutoff_date=date(2025, 9, 24),
        extractor=_extract_fixture,
    ).discover()

    assert len(parse_dated_document_listing(html, source, cutoff_date=date(2025, 9, 24))) == 3
    assert len(result.notices) == 1
    assert http.calls == [source.listing_url, first_url]
    assert any("bounded first 2" in warning for warning in result.warnings)


@pytest.mark.parametrize(("source_code", "fixture_name", "detail_path"), CASES)
def test_each_source_rediscovery_is_idempotent(
    db_session,
    tmp_path,
    source_code: str,
    fixture_name: str,
    detail_path: str,
) -> None:
    source = replace(
        DATED_DOCUMENT_SOURCE_CANDIDATES[source_code],
        max_listing_rows_per_run=1,
        max_notices_per_run=1,
    )
    listing = _fixture(fixture_name)
    direct_url = urljoin(source.listing_url, "/sites/default/files/advertisement-current.pdf")

    def adapter() -> DatedDocumentResolverAdapter:
        return DatedDocumentResolverAdapter(
            _FakeHttp(
                {
                    source.listing_url: _resource(source.listing_url, listing, "text/html"),
                    direct_url: _resource(direct_url, b"%PDF fixture", "application/pdf"),
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
