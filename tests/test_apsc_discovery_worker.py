import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.config import Settings
from app.models.candidates import CandidateField, RecruitmentCandidate, RecruitmentCandidateRevision
from app.models.discovery import DiscoveryRun, DocumentType, SourceDocument
from app.models.evidence import CandidateFieldEvidence, Evidence
from app.models.master import RecruitmentMaster
from app.models.source_registry import RecruitingAuthority, SourceEndpoint
from app.models.verification import VerificationRun
from app.services.apsc_discovery import APSCDiscoveryWorkerService
from app.services.raw_storage import LocalRawStorage
from sources.adapters.apsc_recruitment import (
    AdapterDocument,
    AdapterResult,
    ParsedField,
    parse_portal_feed,
)
from sources.http import FetchedResource


def _result(content: bytes, *, deadline: str = "2026-09-10", warnings=()) -> AdapterResult:
    resource = FetchedResource(
        url="https://apscrecruitment.in/server/api/Advertisement/WhatsNew",
        content=content,
        status_code=200,
        content_type="application/json",
        etag='"fixture"',
        last_modified=None,
        retrieved_at=datetime(2026, 9, 12, tzinfo=UTC),
    )
    fields = parse_portal_feed(content)
    fields = [
        ParsedField(
            field.field_path,
            field.value_type,
            deadline if field.field_path == "application.end_date" else field.value,
            field.raw_value,
            field.source_locator,
            field.excerpt,
            field.context,
        )
        for field in fields
    ]
    return AdapterResult(
        documents=(AdapterDocument(resource, DocumentType.JSON, "json"),),
        extraction_document_index=0,
        fields=tuple(fields),
        warnings=tuple(warnings),
    )


class FakeAdapter:
    def __init__(self, result: AdapterResult) -> None:
        self.result = result

    def discover(self) -> AdapterResult:
        return self.result


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_raw_storage_is_content_addressed_and_portable(tmp_path) -> None:
    storage = LocalRawStorage(tmp_path)
    first = storage.store(source_code="APSC", content=b"official", extension="HTML")
    second = storage.store(source_code="APSC", content=b"official", extension="html")
    assert first.storage_uri.startswith("raw://apsc/")
    assert first.path.read_bytes() == b"official"
    assert first.created is True
    assert second.created is False
    assert first.path == second.path


def test_discovery_pipeline_is_idempotent_versioned_and_stops_before_truth_domains(
    db_session, tmp_path
) -> None:
    fixture = (
        __import__("pathlib").Path(__file__).parent / "fixtures" / "apsc" / "whats_new_12_2026.json"
    ).read_bytes()
    settings = Settings(raw_storage_root=str(tmp_path))
    worker = APSCDiscoveryWorkerService(db_session, settings, logging.getLogger(__name__))

    first = worker.run(adapter=FakeAdapter(_result(fixture)))
    second = worker.run(adapter=FakeAdapter(_result(fixture)))
    changed = fixture.replace(b"10/09/2026", b"11/09/2026")
    third = worker.run(adapter=FakeAdapter(_result(changed, deadline="2026-09-11")))

    assert (first.documents_new, second.documents_unchanged, third.documents_changed) == (1, 1, 1)
    assert (first.candidates_created, second.candidates_reused) == (1, 1)
    assert (first.revisions_created, second.revisions_reused, third.revisions_created) == (1, 1, 1)
    assert _count(db_session, RecruitingAuthority) == 1
    assert _count(db_session, SourceEndpoint) == 1
    assert _count(db_session, RecruitmentCandidate) == 1
    assert _count(db_session, RecruitmentCandidateRevision) == 2
    assert _count(db_session, SourceDocument) == 2
    assert _count(db_session, CandidateFieldEvidence) == _count(db_session, CandidateField)
    assert _count(db_session, Evidence) > 0
    assert _count(db_session, VerificationRun) == 0
    assert _count(db_session, RecruitmentMaster) == 0
    revisions = list(
        db_session.scalars(
            select(RecruitmentCandidateRevision).order_by(
                RecruitmentCandidateRevision.revision_number
            )
        )
    )
    assert [revision.revision_number for revision in revisions] == [1, 2]


def test_partial_run_preserves_official_portal_candidate(db_session, tmp_path) -> None:
    from pathlib import Path

    fixture = (Path(__file__).parent / "fixtures" / "apsc" / "whats_new_12_2026.json").read_bytes()
    worker = APSCDiscoveryWorkerService(
        db_session, Settings(raw_storage_root=str(tmp_path)), logging.getLogger(__name__)
    )
    summary = worker.run(adapter=FakeAdapter(_result(fixture, warnings=("PDF timeout",))))
    assert summary.status == "PARTIAL"
    assert _count(db_session, RecruitmentCandidate) == 1
    assert db_session.scalar(select(DiscoveryRun)).error_code == "DETAIL_DOCUMENT_LIMITATION"


def test_dry_run_rolls_back_database_and_raw_files(db_session, tmp_path) -> None:
    from pathlib import Path

    fixture = (Path(__file__).parent / "fixtures" / "apsc" / "whats_new_12_2026.json").read_bytes()
    summary = APSCDiscoveryWorkerService(
        db_session, Settings(raw_storage_root=str(tmp_path)), logging.getLogger(__name__)
    ).run(dry_run=True, adapter=FakeAdapter(_result(fixture)))
    assert summary.dry_run is True
    assert _count(db_session, DiscoveryRun) == 0
    assert not list(tmp_path.rglob("*"))
