import logging
from datetime import UTC, date, datetime

from sqlalchemy import func, select

from app.core.config import Settings
from app.models.candidates import CandidateField, CandidateValueType, RecruitmentCandidate
from app.models.discovery import DocumentType, SourceDocument
from app.models.evidence import CandidateFieldEvidence, Evidence
from app.models.source_registry import RecruitingAuthority, SourceEndpoint
from app.services.official_archive_discovery import OfficialArchiveDiscoveryWorkerService
from app.services.pipeline_orchestrator import PIPELINE_SOURCES
from sources.adapters.apsc_recruitment import AdapterDocument, ParsedField
from sources.adapters.official_recruitment_archive import (
    OFFICIAL_ARCHIVE_SOURCES,
    ArchiveAdapterResult,
    ArchiveNotice,
    ArchiveNoticeMetadata,
    archive_candidate_key,
    parse_archive_listing,
)
from sources.http import FetchedResource


def _resource(url: str, content: bytes, content_type: str) -> FetchedResource:
    return FetchedResource(
        url=url,
        content=content,
        status_code=200,
        content_type=content_type,
        etag='"fixture"',
        last_modified=None,
        retrieved_at=datetime(2026, 9, 13, tzinfo=UTC),
    )


def test_slprb_listing_selects_only_dated_advertisements_in_window() -> None:
    html = b"""
    <table>
      <tr><td>16/01/2026</td><td>SLPRB/REC/CONST/1/2026</td>
      <td>Advertisement for 100 posts of Constable
      <a href="pdf/Notice2026/adv_constable.pdf">Advertisement</a></td></tr>
      <tr><td>12/01/2026</td><td>SLPRB/RESULT/1</td>
      <td>Result for Constable <a href="result.pdf">Notice</a></td></tr>
      <tr><td>10/01/2023</td><td>SLPRB/REC/OLD</td>
      <td>Advertisement for old posts <a href="adv_old.pdf">Advertisement</a></td></tr>
    </table>
    """

    items = parse_archive_listing(
        html,
        OFFICIAL_ARCHIVE_SOURCES["SLPRB_ASSAM"],
        earliest_year=2024,
    )

    assert len(items) == 1
    assert items[0].title == "Advertisement for 100 posts of Constable"
    assert items[0].notification_number == "SLPRB/REC/CONST/1/2026"
    assert items[0].notification_date == date(2026, 1, 16)
    assert items[0].document_url == "https://slprbassam.in/pdf/Notice2026/adv_constable.pdf"


def test_standard_assam_archive_excludes_results_and_old_advertisements() -> None:
    html = b"""
    <table>
      <tr><td><a href="new.pdf">Advertisement for Teachers (Aug, 2025)</a></td></tr>
      <tr><td><a href="result.pdf">Final Select List for Recruitment 2025</a></td></tr>
      <tr><td><a href="old.pdf">Advertisement for Teachers (Dec, 2023)</a></td></tr>
    </table>
    """

    items = parse_archive_listing(
        html,
        OFFICIAL_ARCHIVE_SOURCES["DEE_ASSAM"],
        earliest_year=2024,
    )

    assert [item.title for item in items] == ["Advertisement for Teachers (Aug, 2025)"]
    assert items[0].notification_date == date(2025, 8, 1)


def test_structured_resource_table_accepts_download_links_and_excludes_lifecycle_docs() -> None:
    html = b"""
    <table>
      <tr><td>Vacancy for the post of District Project Officer</td>
      <td><a href="/download?id=10">Download</a></td><td>20.07.2025</td><td>11-08-2025</td></tr>
      <tr><td>Result of interview for District Project Officer</td>
      <td><a href="/download?id=11">Download</a></td><td>29-12-2025</td><td>N/A</td></tr>
      <tr><td>Notice for cancellation of Advertisement</td>
      <td><a href="/download?id=13">Download</a></td><td>20-12-2025</td><td>N/A</td></tr>
      <tr><td>Vacancy for an old post</td>
      <td><a href="/download?id=12">Download</a></td><td>01-01-2023</td><td>N/A</td></tr>
    </table>
    """

    items = parse_archive_listing(
        html,
        OFFICIAL_ARCHIVE_SOURCES["ASDMA_ASSAM"],
        earliest_year=2024,
    )

    assert len(items) == 1
    assert items[0].title == "Vacancy for the post of District Project Officer"
    assert items[0].notification_date == date(2025, 7, 20)
    assert items[0].document_url == "https://asdma.assam.gov.in/download?id=10"


def test_archive_candidate_key_is_stable_and_authority_scoped() -> None:
    item = ArchiveNoticeMetadata(
        title="Advertisement for Teachers",
        document_url="https://dee.assam.gov.in/files/teachers.pdf",
        notification_number="DEE/1/2025",
        notification_date=date(2025, 8, 1),
    )

    assert archive_candidate_key("DEE_ASSAM", item) == archive_candidate_key("DEE_ASSAM", item)
    assert archive_candidate_key("DEE_ASSAM", item).startswith("DEE_ASSAM_ADVT_2025_")
    assert archive_candidate_key("DME_ASSAM", item) != archive_candidate_key("DEE_ASSAM", item)


def test_all_official_archive_sources_are_pipeline_selectable() -> None:
    assert set(OFFICIAL_ARCHIVE_SOURCES) <= set(PIPELINE_SOURCES)


class _FakeArchiveAdapter:
    def __init__(self, result: ArchiveAdapterResult) -> None:
        self.result = result

    def discover(self) -> ArchiveAdapterResult:
        return self.result


def _adapter_result() -> ArchiveAdapterResult:
    metadata = ArchiveNoticeMetadata(
        title="Advertisement for 100 posts of Constable",
        document_url="https://slprbassam.in/pdf/Notice2026/adv_constable.pdf",
        notification_number="SLPRB/REC/CONST/1/2026",
        notification_date=date(2026, 1, 16),
    )
    excerpt = (
        "STATE LEVEL POLICE RECRUITMENT BOARD, ASSAM. "
        "SLPRB/REC/CONST/1/2026. Advertisement for 100 posts of Constable."
    )
    fields = (
        ParsedField(
            "recruitment_name",
            CandidateValueType.STRING,
            metadata.title,
            metadata.title,
            "pdf:page=1",
            excerpt,
        ),
        ParsedField(
            "organization.name",
            CandidateValueType.STRING,
            "State Level Police Recruitment Board, Assam",
            "State Level Police Recruitment Board, Assam",
            "pdf:page=1",
            excerpt,
        ),
        ParsedField(
            "vacancies.total",
            CandidateValueType.INTEGER,
            100,
            "100",
            "pdf:page=1",
            excerpt,
        ),
    )
    return ArchiveAdapterResult(
        listing_document=AdapterDocument(
            _resource("https://slprbassam.in/", b"<html>official</html>", "text/html"),
            DocumentType.HTML,
            "html",
        ),
        notices=(
            ArchiveNotice(
                metadata=metadata,
                document=AdapterDocument(
                    _resource(metadata.document_url, b"%PDF fixture", "application/pdf"),
                    DocumentType.PDF,
                    "pdf",
                ),
                candidate_key=archive_candidate_key("SLPRB_ASSAM", metadata),
                fields=fields,
            ),
        ),
        warnings=(),
    )


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_archive_discovery_is_idempotent_and_stops_before_verification(
    db_session, tmp_path
) -> None:
    worker = OfficialArchiveDiscoveryWorkerService(
        db_session,
        Settings(raw_storage_root=str(tmp_path)),
        logging.getLogger(__name__),
        OFFICIAL_ARCHIVE_SOURCES["SLPRB_ASSAM"],
    )
    adapter = _FakeArchiveAdapter(_adapter_result())

    first = worker.run(adapter=adapter)
    second = worker.run(adapter=adapter)

    assert (first.candidates_created, second.candidates_reused) == (1, 1)
    assert (first.revisions_created, second.revisions_reused) == (1, 1)
    assert (first.documents_new, second.documents_unchanged) == (2, 2)
    assert _count(db_session, RecruitingAuthority) == 1
    assert _count(db_session, SourceEndpoint) == 1
    assert _count(db_session, SourceDocument) == 2
    assert _count(db_session, RecruitmentCandidate) == 1
    assert _count(db_session, CandidateField) == 3
    assert _count(db_session, Evidence) == 1
    assert _count(db_session, CandidateFieldEvidence) == 3


def test_archive_discovery_dry_run_persists_nothing(db_session, tmp_path) -> None:
    summary = OfficialArchiveDiscoveryWorkerService(
        db_session,
        Settings(raw_storage_root=str(tmp_path)),
        logging.getLogger(__name__),
        OFFICIAL_ARCHIVE_SOURCES["SLPRB_ASSAM"],
    ).run(dry_run=True, adapter=_FakeArchiveAdapter(_adapter_result()))

    assert summary.dry_run is True
    assert _count(db_session, RecruitingAuthority) == 0
    assert _count(db_session, RecruitmentCandidate) == 0
    assert not list(tmp_path.rglob("*"))
