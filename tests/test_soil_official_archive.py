import logging
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import Settings
from app.models.candidates import AdvertisementSplitStatus, CandidateValueType, RecruitmentCandidate
from app.services.official_archive_discovery import OfficialArchiveDiscoveryWorkerService
from app.services.pipeline_orchestrator import PIPELINE_SOURCES
from app.services.source_scheduler import source_schedule_catalog
from sources.adapters.official_recruitment_archive import (
    OFFICIAL_ARCHIVE_SOURCE_CANDIDATES,
    OFFICIAL_ARCHIVE_SOURCES,
    OfficialRecruitmentArchiveAdapter,
    archive_candidate_key,
    parse_archive_listing,
)
from sources.extraction import ParsedAdvertisement, ParsedField
from sources.http import FetchedResource
from sources.post_structure import structure_posts


def _fixture() -> bytes:
    return (Path(__file__).parent / "fixtures" / "soil_archive" / "listing.html").read_bytes()


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


def test_live_validated_soil_source_is_registered_with_bounded_schedule() -> None:
    source = OFFICIAL_ARCHIVE_SOURCE_CANDIDATES["SOIL_ASSAM"]

    assert OFFICIAL_ARCHIVE_SOURCES["SOIL_ASSAM"] == source
    assert "SOIL_ASSAM" in PIPELINE_SOURCES
    assert "SOIL_ASSAM" in source_schedule_catalog()
    assert source.priority == 84
    assert source.requests_per_minute == 4
    assert source.max_notices_per_run == 10


def test_soil_listing_requires_safe_context_and_filters_lifecycle_dates_and_hosts() -> None:
    source = OFFICIAL_ARCHIVE_SOURCE_CANDIDATES["SOIL_ASSAM"]

    items = parse_archive_listing(_fixture(), source, cutoff_date=date(2025, 9, 24))

    assert [item.title for item in items] == [
        "Advertisement for 48 posts of Field Assistant in Soil Conservation",
        "Vacancy for Soil Conservation Demonstrator",
    ]
    assert items[0].notification_date == date(2026, 9, 1)
    assert items[1].notification_date is None
    assert all("example.invalid" not in item.document_url for item in items)


def test_soil_resolves_document_with_deterministic_identity_and_shared_posts() -> None:
    source = replace(OFFICIAL_ARCHIVE_SOURCE_CANDIDATES["SOIL_ASSAM"], max_notices_per_run=1)
    listing = b"""
    <table><tr><td>Advertisement for 48 posts of Field Assistant in Soil Conservation</td>
    <td>01/09/2026</td><td><a href="/files/advertisement-soil.pdf"></a></td></tr></table>
    """
    document_url = "https://soildirectorate.assam.gov.in/files/advertisement-soil.pdf"
    http = _FakeHttp(
        {
            source.listing_url: _resource(source.listing_url, listing, "text/html"),
            document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = OfficialRecruitmentArchiveAdapter(
        http, source, cutoff_date=date(2025, 9, 24), extractor=_extract_fixture
    ).discover()

    assert http.calls == [source.listing_url, document_url]
    assert len(result.notices) == 1
    notice = result.notices[0]
    assert notice.candidate_key == archive_candidate_key(source.authority_code, notice.metadata)
    assert notice.split_status == AdvertisementSplitStatus.EXPLICIT
    assert len(notice.posts) == 1


def test_soil_document_redirect_outside_authority_is_rejected() -> None:
    source = replace(OFFICIAL_ARCHIVE_SOURCE_CANDIDATES["SOIL_ASSAM"], max_notices_per_run=1)
    listing = b"""
    <table><tr><td>Advertisement for Soil Conservation vacancies</td>
    <td><a href="/files/advertisement-soil.pdf"></a></td></tr></table>
    """
    document_url = "https://soildirectorate.assam.gov.in/files/advertisement-soil.pdf"
    http = _FakeHttp(
        {
            source.listing_url: _resource(source.listing_url, listing, "text/html"),
            document_url: _resource(
                "https://example.invalid/redirected.pdf", b"%PDF fixture", "application/pdf"
            ),
        }
    )

    result = OfficialRecruitmentArchiveAdapter(
        http, source, cutoff_date=date(2025, 9, 24), extractor=_extract_fixture
    ).discover()

    assert result.notices == ()
    assert any("redirect left approved source scope" in warning for warning in result.warnings)


def test_soil_rediscovery_is_idempotent(db_session, tmp_path) -> None:
    source = replace(OFFICIAL_ARCHIVE_SOURCE_CANDIDATES["SOIL_ASSAM"], max_notices_per_run=1)
    listing = b"""
    <table><tr><td>Advertisement for 48 posts of Field Assistant in Soil Conservation</td>
    <td>01/09/2026</td><td><a href="/files/advertisement-soil.pdf"></a></td></tr></table>
    """
    document_url = "https://soildirectorate.assam.gov.in/files/advertisement-soil.pdf"

    def adapter() -> OfficialRecruitmentArchiveAdapter:
        return OfficialRecruitmentArchiveAdapter(
            _FakeHttp(
                {
                    source.listing_url: _resource(source.listing_url, listing, "text/html"),
                    document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
                }
            ),
            source,
            cutoff_date=date(2025, 9, 24),
            extractor=_extract_fixture,
        )

    worker = OfficialArchiveDiscoveryWorkerService(
        db_session, Settings(raw_storage_root=str(tmp_path)), logging.getLogger(__name__), source
    )
    first = worker.run(adapter=adapter())
    second = worker.run(adapter=adapter())

    assert (first.candidates_created, second.candidates_reused) == (1, 1)
    assert db_session.scalar(select(func.count()).select_from(RecruitmentCandidate)) == 1
