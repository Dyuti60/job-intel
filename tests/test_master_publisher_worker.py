from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.confidence import RevisionConfidenceAssessment
from app.models.master import (
    MasterChange,
    MasterField,
    MasterPublicationEvent,
    RecruitmentMaster,
    RecruitmentMasterRevision,
)
from app.services.master_publisher_worker import (
    MasterPublisherWorkerService,
    format_master_publisher_summary,
)
from tests.factories import decide_review_item, start_review_case
from tests.test_master_api import _direct_graph
from tests.test_review_api import build_review_graph
from workers import master_publisher as master_publisher_command


def _resolve_case(
    client: TestClient,
    graph: dict,
    decision: str,
    *,
    corrected_value: str | None = None,
) -> None:
    review_case = graph["case"]
    assert review_case is not None
    start_review_case(client, review_case["id"])
    for item in review_case["items"]:
        item_decision = decision
        overrides = {}
        if corrected_value is not None and item["scope"] == "FIELD":
            item_decision = "CORRECT_AND_APPROVE"
            overrides = {
                "corrected_value_type": item["candidate_value_type_snapshot"],
                "corrected_value": corrected_value,
                "decision_note": "Worker correction approved.",
            }
        elif item_decision in {"REJECT", "REQUEST_REVERIFICATION"}:
            overrides = {"decision_note": "Worker routing test decision."}
        decide_review_item(client, item["id"], item_decision, **overrides)


def _count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_direct_publication_and_second_run_are_idempotent(
    client: TestClient, db_session: Session
) -> None:
    _direct_graph(client, "WORKER_DIRECT")

    first = MasterPublisherWorkerService(db_session).run(batch_size=100)
    assert first.scanned == 1
    assert first.direct_verified == 1
    assert first.master_created == 1
    assert first.failed == 0
    counts = (
        _count(db_session, RecruitmentMaster),
        _count(db_session, RecruitmentMasterRevision),
        _count(db_session, MasterField),
        _count(db_session, MasterChange),
        _count(db_session, MasterPublicationEvent),
    )

    second = MasterPublisherWorkerService(db_session).run(batch_size=100)
    assert second.scanned == 0
    assert counts == (
        _count(db_session, RecruitmentMaster),
        _count(db_session, RecruitmentMasterRevision),
        _count(db_session, MasterField),
        _count(db_session, MasterChange),
        _count(db_session, MasterPublicationEvent),
    )


def test_approved_and_corrected_review_paths_publish(
    client: TestClient, db_session: Session
) -> None:
    approved = build_review_graph(client, suffix="WORKER_APPROVED")
    _resolve_case(client, approved, "APPROVE_AS_IS")
    corrected = build_review_graph(client, suffix="WORKER_CORRECTED")
    _resolve_case(client, corrected, "APPROVE_AS_IS", corrected_value="2026-10-27")

    summary = MasterPublisherWorkerService(db_session).run(batch_size=100)

    assert summary.human_approved == 1
    assert summary.human_corrected == 1
    assert summary.master_created == 2
    corrected_field = db_session.scalar(
        select(MasterField).where(MasterField.value_origin == "HUMAN_CORRECTED")
    )
    assert corrected_field is not None
    assert corrected_field.value == "2026-10-27"
    assert corrected_field.review_decision_id is not None
    source_field = next(
        field
        for field in corrected["revision"]["fields"]
        if field["field_path"] == "application.end_date"
    )
    assert source_field["value"] == "2026-10-20"


def test_review_skip_states_are_normal_work(
    client: TestClient, db_session: Session
) -> None:
    missing = build_review_graph(client, suffix="WORKER_MISSING", create_case=False)
    queued = build_review_graph(client, suffix="WORKER_QUEUED")
    in_review = build_review_graph(client, suffix="WORKER_IN_REVIEW")
    start_review_case(client, in_review["case"]["id"])
    rejected = build_review_graph(client, suffix="WORKER_REJECTED")
    _resolve_case(client, rejected, "REJECT")
    reverify = build_review_graph(client, suffix="WORKER_REVERIFY")
    _resolve_case(client, reverify, "REQUEST_REVERIFICATION")

    summary = MasterPublisherWorkerService(db_session).run(batch_size=100)

    assert summary.scanned == 5
    assert summary.review_missing == 1
    assert summary.review_pending == 2
    assert summary.rejected == 1
    assert summary.reverification_requested == 1
    assert summary.failed == 0
    assert _count(db_session, RecruitmentMaster) == 0
    assert missing["confidence"]["id"] in {str(item) for item in summary.scanned_ids}
    assert queued["confidence"]["id"] in {str(item) for item in summary.scanned_ids}


def test_mixed_batch_continues_after_invalid_assessment(
    client: TestClient, db_session: Session
) -> None:
    direct = _direct_graph(client, "WORKER_MIX_DIRECT")
    approved = build_review_graph(client, suffix="WORKER_MIX_APPROVED")
    _resolve_case(client, approved, "APPROVE_AS_IS")
    corrected = build_review_graph(client, suffix="WORKER_MIX_CORRECTED")
    _resolve_case(client, corrected, "APPROVE_AS_IS", corrected_value="2026-10-27")
    pending = build_review_graph(client, suffix="WORKER_MIX_PENDING")
    rejected = build_review_graph(client, suffix="WORKER_MIX_REJECTED")
    _resolve_case(client, rejected, "REJECT")
    invalid = _direct_graph(client, "WORKER_MIX_INVALID")
    invalid_assessment = db_session.get(
        RevisionConfidenceAssessment, UUID(invalid["confidence"]["id"])
    )
    assert invalid_assessment is not None
    invalid_assessment.input_hash = "f" * 64
    db_session.commit()

    summary = MasterPublisherWorkerService(db_session).run(batch_size=100)

    assert summary.scanned == 6
    assert summary.direct_verified == 1
    assert summary.human_approved == 1
    assert summary.human_corrected == 1
    assert summary.review_pending == 1
    assert summary.rejected == 1
    assert summary.failed == 1
    assert summary.master_created == 3
    assert _count(db_session, RecruitmentMaster) == 3
    assert _count(db_session, MasterPublicationEvent) == 3
    assert direct["confidence"]["id"] != pending["confidence"]["id"]


def test_batch_limit_uses_oldest_then_id_order(
    client: TestClient, db_session: Session
) -> None:
    graphs = [_direct_graph(client, f"WORKER_ORDER_{index}") for index in range(3)]
    base = datetime(2026, 1, 1, tzinfo=UTC)
    ordered = [graphs[1], graphs[2], graphs[0]]
    for index, graph in enumerate(ordered):
        assessment = db_session.get(
            RevisionConfidenceAssessment, UUID(graph["confidence"]["id"])
        )
        assert assessment is not None
        assessment.created_at = base + timedelta(minutes=index)
    db_session.commit()
    expected_ids = [UUID(graph["confidence"]["id"]) for graph in ordered[:2]]

    summary = MasterPublisherWorkerService(db_session).run(batch_size=2)

    assert summary.scanned_ids == expected_ids
    assert _count(db_session, MasterPublicationEvent) == 2
    remaining = MasterPublisherWorkerService(db_session).run(batch_size=2)
    assert remaining.scanned == 1


def test_dry_run_validates_and_classifies_without_mutation(
    client: TestClient, db_session: Session
) -> None:
    _direct_graph(client, "WORKER_DRY")

    dry_run = MasterPublisherWorkerService(db_session).run(batch_size=100, dry_run=True)

    assert dry_run.scanned == 1
    assert dry_run.direct_verified == 1
    assert dry_run.master_created == 1
    assert dry_run.status == "DRY_RUN"
    assert _count(db_session, RecruitmentMaster) == 0
    assert _count(db_session, RecruitmentMasterRevision) == 0
    assert _count(db_session, MasterField) == 0
    assert _count(db_session, MasterChange) == 0
    assert _count(db_session, MasterPublicationEvent) == 0
    report = format_master_publisher_summary(dry_run)
    assert "(DRY RUN)" in report
    assert "WOULD RESULT" in report

    actual = MasterPublisherWorkerService(db_session).run(batch_size=100)
    assert actual.master_created == 1


def test_command_prints_summary_and_returns_zero(
    client: TestClient,
    db_session: Session,
    monkeypatch,
    capsys,
) -> None:
    _direct_graph(client, "WORKER_COMMAND")
    monkeypatch.setattr(
        master_publisher_command,
        "get_settings",
        lambda: SimpleNamespace(log_level="WARNING", master_publisher_batch_size=100),
    )
    monkeypatch.setattr(
        master_publisher_command,
        "SessionLocal",
        lambda: nullcontext(db_session),
    )

    assert master_publisher_command.main([]) == 0
    output = capsys.readouterr().out
    assert "Assam Job Intelligence - Master Publisher" in output
    assert "Status: SUCCESS" in output


def test_command_returns_nonzero_for_worker_level_failure(monkeypatch, capsys) -> None:
    class BrokenWorker:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self, **_kwargs):
            raise OSError("database unavailable")

    monkeypatch.setattr(
        master_publisher_command,
        "get_settings",
        lambda: SimpleNamespace(log_level="WARNING", master_publisher_batch_size=100),
    )
    monkeypatch.setattr(
        master_publisher_command,
        "SessionLocal",
        lambda: nullcontext(object()),
    )
    monkeypatch.setattr(master_publisher_command, "MasterPublisherWorkerService", BrokenWorker)

    assert master_publisher_command.main([]) == 1
    assert "failed before the batch could complete" in capsys.readouterr().out
