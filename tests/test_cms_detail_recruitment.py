import logging
from dataclasses import replace
from datetime import UTC, date, datetime
from urllib.parse import urljoin

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.models.candidates import (
    AdvertisementSplitStatus,
    CandidateValueType,
    RecruitmentCandidate,
    RecruitmentPost,
)
from app.services.official_archive_discovery import OfficialArchiveDiscoveryWorkerService
from app.services.pipeline_orchestrator import PIPELINE_SOURCES
from app.services.source_scheduler import source_schedule_catalog
from sources.adapters.cms_detail_recruitment import (
    CMS_DETAIL_SOURCE_CANDIDATES,
    CMS_DETAIL_SOURCES,
    CmsDetailRecruitmentAdapter,
    parse_cms_detail_listing,
)
from sources.extraction import ParsedAdvertisement, ParsedField
from sources.http import FetchedResource
from sources.post_structure import structure_posts


def _resource(url: str, content: bytes, content_type: str) -> FetchedResource:
    return FetchedResource(
        url=url,
        content=content,
        status_code=200,
        content_type=content_type,
        etag='"fixture"',
        last_modified=None,
        retrieved_at=datetime(2026, 9, 21, tzinfo=UTC),
    )


class _FakeHttp:
    def __init__(self, resources: dict[str, FetchedResource]) -> None:
        self.resources = resources
        self.calls: list[str] = []

    def fetch(self, url: str, *, accepted_types: tuple[str, ...]) -> FetchedResource:
        self.calls.append(url)
        resource = self.resources[url]
        media_type = (resource.content_type or "").split(";", 1)[0]
        assert media_type in accepted_types
        return resource


def _extract_fixture(content: bytes, metadata, organization_name):
    assert content == b"%PDF fixture"
    assert organization_name
    posts, split_status, split_note, warnings = structure_posts(metadata.title, "")
    return ParsedAdvertisement(
        fields=(
            ParsedField(
                "notification.date",
                CandidateValueType.DATE,
                "2026-09-01",
                "01/09/2026",
                "pdf:page=1",
                "Dated 01/09/2026",
            ),
        ),
        posts=posts,
        split_status=split_status,
        split_note=split_note,
        warnings=warnings,
    )


@pytest.mark.parametrize("source_code", ["AGRI_ASSAM", "NHM_ASSAM"])
def test_unvalidated_cms_sources_are_not_registered_for_execution(source_code: str) -> None:
    source = CMS_DETAIL_SOURCE_CANDIDATES[source_code]

    assert source_code not in CMS_DETAIL_SOURCES
    assert source_code not in PIPELINE_SOURCES
    assert source_code not in source_schedule_catalog()
    assert source.schedule_group.value == "HIGH_PRIORITY"
    assert source.requests_per_minute == 4
    assert source.max_detail_pages_per_run == 10
    assert source.max_notices_per_run == 10


def test_agriculture_listing_traverses_one_safe_detail_and_document() -> None:
    source = CMS_DETAIL_SOURCE_CANDIDATES["AGRI_ASSAM"]
    detail_url = urljoin(source.listing_url, "/node/94116")
    redirected_detail_url = urljoin(source.listing_url, "/resource/detail/field-assistant")
    document_url = urljoin(source.listing_url, "/files/recruitment-notice.pdf")
    listing = b"""
    <ul>
          <li><a href="/node/94116">
        Advertisement for 48 posts of Field Assistant in Directorate of Agriculture dated 01/09/2026
      </a></li>
      <li><a href="/resource/detail/result">Result of recruitment dated 02/09/2026</a></li>
      <li><a href="https://evil.example/resource/detail/jobs">
        Advertisement for outside posts dated 03/09/2026
      </a></li>
    </ul>
    """
    detail = b"""
    <a href="/files/application-form.pdf">Application Form</a>
    <a href="/files/result.pdf">Result of recruitment</a>
    <a href="https://evil.example/advertisement.pdf">Advertisement</a>
    <a href="/files/recruitment-notice.pdf">Recruitment Notice</a>
    """
    http = _FakeHttp(
        {
            source.listing_url: _resource(source.listing_url, listing, "text/html"),
            detail_url: _resource(redirected_detail_url, detail, "text/html"),
            document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = CmsDetailRecruitmentAdapter(
        http, source, earliest_year=2025, extractor=_extract_fixture
    ).discover()

    assert http.calls == [source.listing_url, detail_url, document_url]
    assert len(result.notices) == 1
    assert result.notices[0].metadata.document_url == document_url
    assert result.notices[0].metadata.title == (
        "Advertisement for 48 posts of Field Assistant in Directorate of Agriculture"
    )
    assert result.notices[0].split_status == AdvertisementSplitStatus.EXPLICIT
    assert [post.name for post in result.notices[0].posts] == [
        "Field Assistant – Directorate of Agriculture"
    ]


def test_nhm_undated_listing_uses_official_document_date_and_shared_post_structuring() -> None:
    source = CMS_DETAIL_SOURCE_CANDIDATES["NHM_ASSAM"]
    detail_url = urljoin(source.listing_url, "/latest/advertisement-for-field-assistant")
    document_url = urljoin(source.listing_url, "/files/advertisement.pdf")
    listing = b"""
    <h2><a href="/latest/advertisement-for-field-assistant">
      Advertisement for 48 posts of Field Assistant in Assam
    </a></h2>
    """
    detail = b'<a href="/files/advertisement.pdf">Advertisement</a>'
    http = _FakeHttp(
        {
            source.listing_url: _resource(source.listing_url, listing, "text/html"),
            detail_url: _resource(detail_url, detail, "text/html"),
            document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
        }
    )

    result = CmsDetailRecruitmentAdapter(
        http, source, earliest_year=2025, extractor=_extract_fixture
    ).discover()

    assert len(result.notices) == 1
    assert result.notices[0].metadata.notification_date == date(2026, 9, 1)
    assert result.notices[0].posts[0].name == "Field Assistant – Assam"


def test_cms_listing_is_same_domain_bounded_and_malformed_detail_is_skipped() -> None:
    source = replace(CMS_DETAIL_SOURCE_CANDIDATES["AGRI_ASSAM"], max_detail_pages_per_run=1)
    listing = b"""
    <a href="/resource/detail/newest">Vacancy for Newest Post dated 03/09/2026</a>
    <a href="/resource/detail/older">Vacancy for Older Post dated 02/09/2026</a>
    <a href="https://evil.example/resource/detail/outside">
      Vacancy for Outside Post dated 04/09/2026
    </a>
    """
    detail_url = urljoin(source.listing_url, "/resource/detail/newest")
    http = _FakeHttp(
        {
            source.listing_url: _resource(source.listing_url, listing, "text/html"),
            detail_url: _resource(
                detail_url,
                b'<a href="/files/application-form.pdf">Application Form</a>',
                "text/html",
            ),
        }
    )

    result = CmsDetailRecruitmentAdapter(
        http, source, earliest_year=2025, extractor=_extract_fixture
    ).discover()

    assert http.calls == [source.listing_url, detail_url]
    assert result.notices == ()
    assert any("processed bounded first 1" in warning for warning in result.warnings)
    assert any("No recruitment document" in warning for warning in result.warnings)


def test_listing_excludes_lifecycle_old_and_unsupported_links() -> None:
    source = CMS_DETAIL_SOURCE_CANDIDATES["AGRI_ASSAM"]
    html = b"""
    <a href="/resource/detail/open">Recruitment notice dated 01/09/2026</a>
    <a href="/resource/detail/result">Merit list for recruitment dated 01/09/2026</a>
    <a href="/resource/detail/corrigendum">Corrigendum to advertisement dated 01/09/2026</a>
    <a href="/resource/detail/old">Recruitment notice dated 01/09/2024</a>
    <a href="/about-us">Recruitment notice dated 01/09/2026</a>
    """

    links = parse_cms_detail_listing(html, source, earliest_year=2025)

    assert [link.url for link in links] == [
        urljoin(source.listing_url, "/resource/detail/open")
    ]


@pytest.mark.parametrize("source_code", ["AGRI_ASSAM", "NHM_ASSAM"])
def test_cms_rediscovery_is_idempotent(db_session, tmp_path, source_code: str) -> None:
    source = CMS_DETAIL_SOURCE_CANDIDATES[source_code]
    detail_path = source.detail_path_prefixes[0] + "field-assistant"
    detail_url = urljoin(source.listing_url, detail_path)
    document_url = urljoin(source.listing_url, "/files/advertisement.pdf")
    dated_title = "Advertisement for 48 posts of Field Assistant in Assam dated 01/09/2026"
    listing = f'<a href="{detail_path}">{dated_title}</a>'.encode()
    detail = b'<a href="/files/advertisement.pdf">Advertisement</a>'

    def adapter() -> CmsDetailRecruitmentAdapter:
        return CmsDetailRecruitmentAdapter(
            _FakeHttp(
                {
                    source.listing_url: _resource(source.listing_url, listing, "text/html"),
                    detail_url: _resource(detail_url, detail, "text/html"),
                    document_url: _resource(document_url, b"%PDF fixture", "application/pdf"),
                }
            ),
            source,
            earliest_year=2025,
            extractor=_extract_fixture,
        )

    worker = OfficialArchiveDiscoveryWorkerService(
        db_session, Settings(raw_storage_root=str(tmp_path)), logging.getLogger(__name__), source
    )
    first = worker.run(adapter=adapter())
    second = worker.run(adapter=adapter())

    assert (first.candidates_created, second.candidates_reused) == (1, 1)
    assert (first.revisions_created, second.revisions_reused) == (1, 1)
    assert db_session.scalar(select(func.count()).select_from(RecruitmentCandidate)) == 1
    assert db_session.scalar(select(func.count()).select_from(RecruitmentPost)) == 1
