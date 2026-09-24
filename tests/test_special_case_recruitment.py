import logging
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urljoin

from sqlalchemy import func, select

from app.core.config import Settings
from app.models.candidates import AdvertisementSplitStatus, CandidateValueType, RecruitmentCandidate
from app.services.official_archive_discovery import OfficialArchiveDiscoveryWorkerService
from app.services.pipeline_orchestrator import PIPELINE_SOURCES
from app.services.source_scheduler import source_schedule_catalog
from sources.adapters.official_recruitment_archive import archive_candidate_key
from sources.adapters.special_case_recruitment import (
    SPECIAL_CASE_SOURCE_CANDIDATES,
    SPECIAL_CASE_SOURCES,
    SpecialCaseRecruitmentAdapter,
)
from sources.extraction import ParsedAdvertisement, ParsedField
from sources.http import FetchedResource
from sources.post_structure import structure_posts


def _fixture(name: str) -> bytes:
    return (Path(__file__).parent / "fixtures" / "special_case" / name).read_bytes()


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
    fields = [
        ParsedField(
            "organization.name",
            CandidateValueType.STRING,
            organization_name,
            organization_name,
            "pdf:page=1",
            organization_name,
        )
    ]
    if "ADRE" in metadata.title:
        fields.append(
            ParsedField(
                "notification.number",
                CandidateValueType.STRING,
                "SLRC-G-III/91/2026/1",
                "SLRC-G-III/91/2026/1",
                "pdf:page=1",
                "Advertisement No. SLRC-G-III/91/2026/1",
            )
        )
    return ParsedAdvertisement(
        fields=tuple(fields),
        posts=posts,
        split_status=split_status,
        split_note=split_note,
        warnings=warnings,
    )


def test_special_case_candidates_remain_unregistered_until_live_validation() -> None:
    assert SPECIAL_CASE_SOURCES == {}
    assert set(SPECIAL_CASE_SOURCE_CANDIDATES) == {"GHC_ASSAM", "SLRC_ASSAM"}
    assert not set(SPECIAL_CASE_SOURCE_CANDIDATES) & set(PIPELINE_SOURCES)
    assert not set(SPECIAL_CASE_SOURCE_CANDIDATES) & set(source_schedule_catalog())


def test_ghc_accepts_only_explicit_assam_principal_seat_notice() -> None:
    source = replace(
        SPECIAL_CASE_SOURCE_CANDIDATES["GHC_ASSAM"],
        max_listing_rows_per_run=5,
        max_detail_pages_per_run=1,
        max_notices_per_run=1,
    )
    detail_url = urljoin(source.listing_url, "/index.php/recruitment-notices/lda-assam")
    document_url = urljoin(source.listing_url, "/recruitment/lda-principal-seat.pdf")
    http = _FakeHttp(
        {
            source.listing_url: _resource(
                source.listing_url, _fixture("ghc_listing.html"), "text/html"
            ),
            detail_url: _resource(detail_url, _fixture("ghc_detail.html"), "text/html"),
            document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = SpecialCaseRecruitmentAdapter(
        http, source, cutoff_date=date(2025, 9, 24), extractor=_extract_fixture
    ).discover()

    assert http.calls == [source.listing_url, detail_url, document_url]
    assert len(result.notices) == 1
    notice = result.notices[0]
    assert notice.candidate_key == archive_candidate_key(source.authority_code, notice.metadata)
    assert notice.split_status == AdvertisementSplitStatus.AMBIGUOUS
    assert notice.posts == ()
    assert not any("kohima" in call or "technical-assistant" in call for call in http.calls)


def test_slrc_accepts_dated_and_undated_campaign_notices_only() -> None:
    source = replace(
        SPECIAL_CASE_SOURCE_CANDIDATES["SLRC_ASSAM"],
        max_listing_rows_per_run=2,
        max_detail_pages_per_run=2,
        max_notices_per_run=2,
    )
    dated_detail = urljoin(source.listing_url, "/adre-2026/advertisement")
    undated_detail = urljoin(source.listing_url, "/adre-2026/grade-iv")
    document_url = urljoin(source.listing_url, "/documents/adre-2026-advertisement.pdf")
    http = _FakeHttp(
        {
            source.listing_url: _resource(
                source.listing_url, _fixture("slrc_listing.html"), "text/html"
            ),
            dated_detail: _resource(dated_detail, _fixture("slrc_detail.html"), "text/html"),
            undated_detail: _resource(undated_detail, _fixture("slrc_detail.html"), "text/html"),
            document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = SpecialCaseRecruitmentAdapter(
        http, source, cutoff_date=date(2025, 9, 24), extractor=_extract_fixture
    ).discover()

    assert len(result.notices) == 1
    assert result.notices[0].candidate_key.startswith("SLRC_ASSAM_ADVT_2026_")
    assert undated_detail in http.calls
    assert not any("answer-key" in call or "adre-2024" in call for call in http.calls)


def test_slrc_requires_stable_reference_and_year() -> None:
    source = replace(
        SPECIAL_CASE_SOURCE_CANDIDATES["SLRC_ASSAM"],
        max_listing_rows_per_run=1,
        max_detail_pages_per_run=1,
        max_notices_per_run=1,
    )
    listing = b'<a href="/campaign/advertisement">ADRE Advertisement for vacancies</a>'
    detail_url = urljoin(source.listing_url, "/campaign/advertisement")
    document_url = urljoin(source.listing_url, "/documents/adre.pdf")
    detail = b'<a href="/documents/adre.pdf">Official recruitment advertisement</a>'
    http = _FakeHttp(
        {
            source.listing_url: _resource(source.listing_url, listing, "text/html"),
            detail_url: _resource(detail_url, detail, "text/html"),
            document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = SpecialCaseRecruitmentAdapter(
        http, source, cutoff_date=date(2025, 9, 24), extractor=_extract_fixture
    ).discover()

    assert result.notices == ()
    assert any("identity could not be established" in warning for warning in result.warnings)


def test_ghc_rediscovery_is_idempotent(db_session, tmp_path) -> None:
    source = replace(
        SPECIAL_CASE_SOURCE_CANDIDATES["GHC_ASSAM"],
        max_listing_rows_per_run=1,
        max_detail_pages_per_run=1,
        max_notices_per_run=1,
    )
    detail_url = urljoin(source.listing_url, "/index.php/recruitment-notices/lda-assam")
    document_url = urljoin(source.listing_url, "/recruitment/lda-principal-seat.pdf")

    def adapter() -> SpecialCaseRecruitmentAdapter:
        return SpecialCaseRecruitmentAdapter(
            _FakeHttp(
                {
                    source.listing_url: _resource(
                        source.listing_url, _fixture("ghc_listing.html"), "text/html"
                    ),
                    detail_url: _resource(detail_url, _fixture("ghc_detail.html"), "text/html"),
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


def test_slrc_alternate_official_url_reuses_stable_campaign_candidate(db_session, tmp_path) -> None:
    source = replace(
        SPECIAL_CASE_SOURCE_CANDIDATES["SLRC_ASSAM"],
        max_listing_rows_per_run=1,
        max_detail_pages_per_run=1,
        max_notices_per_run=1,
    )
    title = "ADRE 2026 Advertisement for 48 posts of Grade III in Assam"
    document_urls = (
        urljoin(source.listing_url, "/documents/adre-2026.pdf"),
        "https://sebaonline.org/documents/adre-2026-canonical.pdf",
    )

    def adapter(index: int) -> SpecialCaseRecruitmentAdapter:
        detail_url = urljoin(source.listing_url, f"/adre-2026/advertisement-{index}")
        listing = f'<a href="{detail_url}">{title}</a>'.encode()
        detail = f'<a href="{document_urls[index]}">Official recruitment advertisement</a>'.encode()
        return SpecialCaseRecruitmentAdapter(
            _FakeHttp(
                {
                    source.listing_url: _resource(source.listing_url, listing, "text/html"),
                    detail_url: _resource(detail_url, detail, "text/html"),
                    document_urls[index]: _resource(
                        document_urls[index], b"%PDF fixture", "application/pdf"
                    ),
                }
            ),
            source,
            cutoff_date=date(2025, 9, 24),
            extractor=_extract_fixture,
        )

    worker = OfficialArchiveDiscoveryWorkerService(
        db_session, Settings(raw_storage_root=str(tmp_path)), logging.getLogger(__name__), source
    )
    first = worker.run(adapter=adapter(0))
    second = worker.run(adapter=adapter(1))

    assert (first.candidates_created, second.candidates_reused) == (1, 1)
    assert db_session.scalar(select(func.count()).select_from(RecruitmentCandidate)) == 1
