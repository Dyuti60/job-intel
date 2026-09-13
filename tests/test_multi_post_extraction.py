import logging
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import Settings
from app.models.candidates import (
    AdvertisementRevision,
    AdvertisementSplitStatus,
    PostFact,
    RecruitmentPost,
)
from app.models.discovery import DocumentType
from app.models.evidence import CandidateFieldEvidence, Evidence
from app.services.official_archive_discovery import OfficialArchiveDiscoveryWorkerService
from sources.adapters.apsc_recruitment import AdapterDocument
from sources.adapters.official_recruitment_archive import (
    OFFICIAL_ARCHIVE_SOURCES,
    ArchiveAdapterResult,
    ArchiveNotice,
    ArchiveNoticeMetadata,
    archive_candidate_key,
    parse_official_advertisement_text,
)
from sources.http import FetchedResource

FIXTURES = Path(__file__).parent / "fixtures" / "slprb"


def _metadata() -> ArchiveNoticeMetadata:
    return ArchiveNoticeMetadata(
        title="Advertisement for Grade IV Staff",
        document_url="https://slprbassam.in/pdf/grade-iv-2026.pdf",
        notification_number="SLPRB/REC/2026/44",
        notification_date=date(2026, 9, 14),
    )


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_multi_post_vacancy_table_is_explicit_and_preserves_shared_facts() -> None:
    extraction = parse_official_advertisement_text(
        _text("multi_post_advertisement.txt"),
        _metadata(),
        "State Level Police Recruitment Board, Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert [post.name for post in extraction.posts] == ["Grade IV Staff"] * 3
    assert [
        next(fact.value for fact in post.facts if fact.field_path == "vacancies.total")
        for post in extraction.posts
    ] == [181, 6, 69]
    assert [post.post_key for post in extraction.posts] == [
        "grade_iv_staff_assam_police",
        "grade_iv_staff_assam_commando_battalions",
        "grade_iv_staff_dgcd_cghg",
    ]
    assert all(
        next(fact.value for fact in post.facts if fact.field_path == "qualification.minimum")
        == "Class VIII passed"
        for post in extraction.posts
    )
    shared = {field.field_path: field.value for field in extraction.fields}
    assert shared["application.start_date"] == "2026-09-20"
    assert shared["application.end_date"] == "2026-10-20"
    assert "vacancies.total" not in shared


def test_malformed_vacancy_table_is_ambiguous_and_fabricates_no_posts() -> None:
    extraction = parse_official_advertisement_text(
        _text("ambiguous_vacancy_table.txt"),
        _metadata(),
        "State Level Police Recruitment Board, Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.AMBIGUOUS
    assert extraction.posts == ()
    assert "expected 9" in extraction.split_note
    assert extraction.warnings


def test_ambiguous_post_detail_ownership_is_retained_without_guessing() -> None:
    extraction = parse_official_advertisement_text(
        _text("ambiguous_post_details.txt"),
        _metadata(),
        "State Level Police Recruitment Board, Assam",
    )

    assert extraction.split_status == AdvertisementSplitStatus.EXPLICIT
    assert len(extraction.posts) == 2
    assert all(
        "qualification.minimum" not in {fact.field_path for fact in post.facts}
        for post in extraction.posts
    )
    ambiguity = next(
        field for field in extraction.fields if field.field_path == "extraction.ambiguities"
    )
    assert ambiguity.value == [
        "Post detail row at pdf:table=post-details-8;row=1 matches 2 vacancy posts"
    ]
    assert extraction.warnings == tuple(ambiguity.value)


class _FakeAdapter:
    def __init__(self, result: ArchiveAdapterResult) -> None:
        self.result = result

    def discover(self) -> ArchiveAdapterResult:
        return self.result


def _resource(url: str, content: bytes, content_type: str) -> FetchedResource:
    return FetchedResource(
        url=url,
        content=content,
        content_type=content_type,
        status_code=200,
        etag=None,
        last_modified=None,
        retrieved_at=datetime(2026, 9, 14, tzinfo=UTC),
    )


def test_archive_worker_persists_post_facts_and_evidence_idempotently(
    db_session, tmp_path
) -> None:
    metadata = _metadata()
    content = _text("multi_post_advertisement.txt").encode()
    extraction = parse_official_advertisement_text(
        content.decode(), metadata, "State Level Police Recruitment Board, Assam"
    )
    result = ArchiveAdapterResult(
        listing_document=AdapterDocument(
            _resource("https://slprbassam.in/", b"<html>official</html>", "text/html"),
            DocumentType.HTML,
            "html",
        ),
        notices=(
            ArchiveNotice(
                metadata=metadata,
                document=AdapterDocument(
                    _resource(metadata.document_url, content, "application/pdf"),
                    DocumentType.PDF,
                    "pdf",
                ),
                candidate_key=archive_candidate_key("SLPRB_ASSAM", metadata),
                fields=extraction.fields,
                posts=extraction.posts,
                split_status=extraction.split_status,
                split_note=extraction.split_note,
            ),
        ),
        warnings=(),
    )
    worker = OfficialArchiveDiscoveryWorkerService(
        db_session,
        Settings(raw_storage_root=str(tmp_path)),
        logging.getLogger(__name__),
        OFFICIAL_ARCHIVE_SOURCES["SLPRB_ASSAM"],
    )

    first = worker.run(adapter=_FakeAdapter(result))
    second = worker.run(adapter=_FakeAdapter(result))

    interpretation = db_session.scalar(select(AdvertisementRevision))
    assert interpretation.split_status == AdvertisementSplitStatus.EXPLICIT
    assert interpretation.detected_post_count == 3
    assert db_session.scalar(select(func.count()).select_from(RecruitmentPost)) == 3
    assert db_session.scalar(select(func.count()).select_from(PostFact)) == 36
    assert db_session.scalar(select(func.count()).select_from(Evidence)) == 37
    assert db_session.scalar(select(func.count()).select_from(CandidateFieldEvidence)) == 43
    assert first.revisions_created == 1
    assert second.revisions_reused == 1
