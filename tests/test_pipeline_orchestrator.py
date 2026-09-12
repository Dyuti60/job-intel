import logging
from contextlib import nullcontext
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.config import Settings
from app.models.candidates import (
    CandidateField,
    CandidateValueType,
    RecruitmentCandidateRevision,
)
from app.models.confidence import RevisionConfidenceAssessment
from app.models.discovery import DiscoveryRun, DocumentType, SourceDocument
from app.models.evidence import Evidence
from app.models.master import MasterField, MasterPublicationEvent, RecruitmentMaster
from app.models.review import ReviewCase
from app.models.verification import VerificationRun
from app.services.pipeline_orchestrator import (
    PipelineOrchestratorService,
    PipelineStatus,
    format_pipeline_summary,
)
from sources.adapters.apsc_recruitment import AdapterDocument, AdapterResult, ParsedField
from sources.http import FetchedResource
from tests.factories import decide_review_item, start_review_case
from workers import pipeline as pipeline_command


class FakeAdapter:
    def __init__(self, result: AdapterResult) -> None:
        self.result = result

    def discover(self) -> AdapterResult:
        return self.result


class BrokenAdapter:
    def discover(self) -> AdapterResult:
        raise OSError("controlled discovery failure")


def _adapter(
    *,
    content: bytes = b"official-v1",
    deadline: str = "2026-10-20",
    review_required: bool = False,
    warnings: tuple[str, ...] = (),
) -> FakeAdapter:
    resource = FetchedResource(
        url="https://apsc.nic.in/advt_2026/Advt_no_12-2026_website.pdf",
        content=content,
        status_code=200,
        content_type="application/pdf",
        etag='"pipeline-fixture"',
        last_modified=None,
        retrieved_at=datetime(2026, 9, 12, tzinfo=UTC),
    )
    deadline_excerpt = (
        "Applications close according to the official schedule."
        if review_required
        else f"Application End Date: {datetime.fromisoformat(deadline).strftime('%d/%m/%Y')}"
    )
    fields = (
        ParsedField(
            "application.end_date",
            CandidateValueType.DATE,
            deadline,
            deadline,
            "fixture:deadline",
            deadline_excerpt,
        ),
        ParsedField(
            "recruitment_name",
            CandidateValueType.STRING,
            "Research Assistant",
            "Research Assistant",
            "fixture:name",
            "Research Assistant under Labour Welfare Department",
        ),
        ParsedField(
            "vacancies.total",
            CandidateValueType.INTEGER,
            1,
            "01",
            "fixture:vacancies",
            "No of posts:-01 (One) no.",
        ),
    )
    return FakeAdapter(
        AdapterResult(
            documents=(AdapterDocument(resource, DocumentType.PDF, "pdf"),),
            extraction_document_index=0,
            fields=fields,
            warnings=warnings,
        )
    )


def _settings(tmp_path) -> Settings:
    return Settings(raw_storage_root=str(tmp_path))


def _run(db_session, tmp_path, adapter, *, dry_run: bool = False):
    return PipelineOrchestratorService(
        db_session, _settings(tmp_path), logging.getLogger(__name__)
    ).run(source="APSC", dry_run=dry_run, discovery_adapter=adapter)


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _resolve(client, case_id: str, *, decision: str, corrected: str | None = None) -> None:
    review_case = client.get(f"/api/v1/review-cases/{case_id}").json()
    start_review_case(client, case_id)
    for item in review_case["items"]:
        item_decision = decision
        overrides = {}
        if corrected is not None and item["scope"] == "FIELD":
            item_decision = "CORRECT_AND_APPROVE"
            overrides = {
                "corrected_value_type": item["candidate_value_type_snapshot"],
                "corrected_value": corrected,
                "decision_note": "Controlled pipeline correction.",
            }
        elif decision in {"REJECT", "REQUEST_REVERIFICATION"}:
            overrides["decision_note"] = "Controlled pipeline routing decision."
        decide_review_item(client, item["id"], item_decision, **overrides)


def test_no_review_pipeline_publishes_and_replay_is_idempotent(db_session, tmp_path) -> None:
    first = _run(db_session, tmp_path, _adapter())
    assert first.status == PipelineStatus.SUCCESS
    assert first.discovery.documents_new == 1
    assert first.verification.completed == 1
    assert first.verification.fields_confirmed == 3
    assert first.publisher.master_created == 1
    assert first.active_review_cases == 0
    counts = tuple(
        _count(db_session, model)
        for model in (
            SourceDocument,
            RecruitmentCandidateRevision,
            VerificationRun,
            RevisionConfidenceAssessment,
            ReviewCase,
            RecruitmentMaster,
            MasterPublicationEvent,
        )
    )

    second = _run(db_session, tmp_path, _adapter())
    assert second.discovery.documents_unchanged == 1
    assert second.verification.revisions_scanned == 0
    assert second.publisher.scanned == 0
    assert counts == tuple(
        _count(db_session, model)
        for model in (
            SourceDocument,
            RecruitmentCandidateRevision,
            VerificationRun,
            RevisionConfidenceAssessment,
            ReviewCase,
            RecruitmentMaster,
            MasterPublicationEvent,
        )
    )


def test_review_required_is_success_and_publisher_skips(db_session, tmp_path) -> None:
    summary = _run(db_session, tmp_path, _adapter(review_required=True))
    assert summary.status == PipelineStatus.SUCCESS
    assert summary.verification.review_cases_queued == 1
    assert summary.publisher.review_pending == 1
    assert summary.active_review_cases == 1
    assert _count(db_session, RecruitmentMaster) == 0


def test_human_correction_publishes_on_later_unchanged_run(
    client, db_session, tmp_path
) -> None:
    first = _run(db_session, tmp_path, _adapter(review_required=True))
    case_id = str(db_session.scalar(select(ReviewCase.id)))
    _resolve(client, case_id, decision="APPROVE_AS_IS", corrected="2026-10-27")
    db_session.rollback()

    second = _run(db_session, tmp_path, _adapter(review_required=True))
    assert second.discovery.documents_unchanged == 1
    assert second.verification.revisions_scanned == 0
    assert second.publisher.human_corrected == 1
    assert second.publisher.master_created == 1
    master_field = db_session.scalar(
        select(MasterField).where(MasterField.field_path == "application.end_date")
    )
    candidate_field = db_session.scalar(
        select(CandidateField).where(CandidateField.field_path == "application.end_date")
    )
    assert master_field.value == "2026-10-27"
    assert master_field.review_decision_id is not None
    assert candidate_field.value == "2026-10-20"
    assert first.publisher.review_pending == 1


def test_rejected_review_remains_unpublished(client, db_session, tmp_path) -> None:
    _run(db_session, tmp_path, _adapter(review_required=True))
    case_id = str(db_session.scalar(select(ReviewCase.id)))
    _resolve(client, case_id, decision="REJECT")
    db_session.rollback()
    second = _run(db_session, tmp_path, _adapter(review_required=True))
    assert second.publisher.rejected == 1
    assert second.status == PipelineStatus.SUCCESS
    assert _count(db_session, RecruitmentMaster) == 0


def test_reverification_request_runs_once_without_loop(client, db_session, tmp_path) -> None:
    _run(db_session, tmp_path, _adapter(review_required=True))
    case_id = str(db_session.scalar(select(ReviewCase.id)))
    _resolve(client, case_id, decision="REQUEST_REVERIFICATION")
    db_session.rollback()

    retry = _run(db_session, tmp_path, _adapter(review_required=True))
    assert retry.verification.completed == 1
    assert _count(db_session, VerificationRun) == 2
    assert _count(db_session, ReviewCase) == 2
    replay = _run(db_session, tmp_path, _adapter(review_required=True))
    assert replay.verification.revisions_scanned == 0
    assert _count(db_session, VerificationRun) == 2


def test_changed_and_partial_discovery_continue_downstream(db_session, tmp_path) -> None:
    first = _run(db_session, tmp_path, _adapter())
    changed = _run(
        db_session,
        tmp_path,
        _adapter(
            content=b"official-v2",
            deadline="2026-10-27",
            warnings=("Optional detail unavailable",),
        ),
    )
    assert first.publisher.master_created == 1
    assert changed.status == PipelineStatus.PARTIAL
    assert changed.discovery.documents_changed == 1
    assert changed.verification.completed == 1
    assert changed.publisher.master_updated == 1
    assert _count(db_session, SourceDocument) == 2
    assert _count(db_session, RecruitmentCandidateRevision) == 2
    assert _count(db_session, VerificationRun) == 2


def test_fatal_discovery_short_circuits_later_stages(db_session, tmp_path) -> None:
    summary = _run(db_session, tmp_path, BrokenAdapter())
    assert summary.status == PipelineStatus.FAILED
    assert summary.verification is None
    assert summary.publisher is None
    assert _count(db_session, DiscoveryRun) == 0
    assert _count(db_session, VerificationRun) == 0
    assert _count(db_session, RecruitmentMaster) == 0


def test_full_dry_run_and_combined_summary_have_no_mutations(db_session, tmp_path) -> None:
    summary = _run(db_session, tmp_path, _adapter(), dry_run=True)
    assert summary.status == PipelineStatus.SUCCESS
    assert summary.discovery.dry_run is True
    assert summary.verification.dry_run is True
    assert summary.publisher.dry_run is True
    for model in (
        DiscoveryRun,
        SourceDocument,
        Evidence,
        VerificationRun,
        ReviewCase,
        RecruitmentMaster,
    ):
        assert _count(db_session, model) == 0
    assert not list(tmp_path.rglob("*"))
    output = format_pipeline_summary(summary)
    assert "Assam Job Intelligence - Pipeline (DRY RUN)" in output
    assert "DISCOVERY" in output
    assert "VERIFICATION" in output
    assert "MASTER PUBLISHER" in output
    assert "Status: SUCCESS" in output


def test_pipeline_command_prints_summary_and_returns_expected_exit(
    monkeypatch, capsys, db_session, tmp_path
) -> None:
    settings = _settings(tmp_path)
    expected = _run(db_session, tmp_path, _adapter())

    class StubPipeline:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self, **_kwargs):
            return expected

    monkeypatch.setattr(pipeline_command, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline_command, "SessionLocal", lambda: nullcontext(db_session))
    monkeypatch.setattr(pipeline_command, "PipelineOrchestratorService", StubPipeline)
    assert pipeline_command.main(["--source", "APSC"]) == 0
    assert "Status: SUCCESS" in capsys.readouterr().out

    expected.status = PipelineStatus.FAILED
    assert pipeline_command.main(["--source", "APSC"]) == 1
