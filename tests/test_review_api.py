from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.confidence import FieldConfidenceAssessment, RevisionConfidenceAssessment
from app.models.review import ReviewCase, ReviewDecision, ReviewItem
from tests.factories import (
    add_verification_assessment,
    complete_verification_run,
    create_authority,
    create_endpoint,
    create_evidence,
    create_field_verification,
    create_ready_candidate_revision,
    create_review_case,
    create_revision_confidence,
    create_run,
    create_verification_run,
    decide_review_item,
    finalize_field_verification,
    observe_document,
    start_review_case,
    start_verification_run,
)


def _different_value(value_type: str, value: Any) -> Any:
    if value_type == "INTEGER":
        return int(value) + 1
    return {
        "DATE": "2026-10-25",
        "DECIMAL": "999.5",
        "STRING": "different",
        "BOOLEAN": not value,
        "DATETIME": "2026-10-25T00:00:00Z",
        "JSON": {"different": True},
    }[value_type]


def _secondary_evidence(
    client: TestClient, *, suffix: str, source_class: str = "SECONDARY_DISCOVERY_ONLY"
) -> dict:
    compact_suffix = suffix[:40]
    authority = create_authority(
        client,
        code=f"REVIEW_SOURCE_{compact_suffix}",
        name=f"Review source {suffix}",
        official_website_url=f"https://review-{suffix.lower()}.example.gov.in",
    )
    endpoint = create_endpoint(
        client,
        authority["id"],
        canonical_url=f"https://review-{suffix.lower()}.example.gov.in/notices",
        source_class=source_class,
    )
    run = create_run(client, endpoint["id"])
    document = observe_document(
        client,
        run["id"],
        document_url=f"https://review-{suffix.lower()}.example.gov.in/item.pdf",
        content_text=f"Review source {suffix} content",
    )["document"]
    return create_evidence(client, document["id"], excerpt=f"Review evidence {suffix}")


def build_review_graph(
    client: TestClient,
    *,
    suffix: str,
    fields: list[dict] | None = None,
    modes: dict[str, str] | None = None,
    create_case: bool = True,
) -> dict:
    fields = fields or [
        {
            "field_path": "application.end_date",
            "value_type": "DATE",
            "value": "2026-10-20",
        }
    ]
    modes = modes or {field["field_path"]: "none" for field in fields}
    authority, document, candidate, revision = create_ready_candidate_revision(
        client,
        fields=fields,
        authority_overrides={
            "code": f"REVIEW_{suffix}",
            "name": f"Review authority {suffix}",
            "official_website_url": f"https://review-{suffix.lower()}.gov.in",
        },
        endpoint_overrides={"canonical_url": f"https://review-{suffix.lower()}.gov.in/notices"},
    )
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    verifications = []
    evidence_records = []
    for index, field in enumerate(revision["fields"]):
        verification = create_field_verification(client, run["id"], field["id"])
        mode = modes[field["field_path"]]
        if mode in {"auth_support", "auth_support_secondary_conflict", "auth_conflict"}:
            evidence = create_evidence(
                client,
                document["id"],
                excerpt=f"Official evidence for {field['field_path']}",
            )
            evidence_records.append(evidence)
            assessment = "CONTRADICTS" if mode == "auth_conflict" else "SUPPORTS"
            asserted_value = (
                _different_value(field["value_type"], field["value"])
                if assessment == "CONTRADICTS"
                else field["value"]
            )
            add_verification_assessment(
                client,
                verification["id"],
                evidence["id"],
                assessment,
                asserted_value=asserted_value,
                asserted_value_type=field["value_type"],
            )
        if mode in {"secondary_support", "auth_support_secondary_conflict"}:
            evidence = _secondary_evidence(client, suffix=f"{suffix}_{index}_{mode}")
            evidence_records.append(evidence)
            assessment = "CONTRADICTS" if mode == "auth_support_secondary_conflict" else "SUPPORTS"
            add_verification_assessment(
                client,
                verification["id"],
                evidence["id"],
                assessment,
                asserted_value=(
                    _different_value(field["value_type"], field["value"])
                    if assessment == "CONTRADICTS"
                    else field["value"]
                ),
                asserted_value_type=field["value_type"],
            )
        finalize_field_verification(client, verification["id"])
        verifications.append(client.get(f"/api/v1/field-verifications/{verification['id']}").json())
    complete_verification_run(client, run["id"])
    confidence = create_revision_confidence(client, run["id"])
    review_case = (
        create_review_case(client, confidence["id"])
        if create_case and confidence["review_required"]
        else None
    )
    return {
        "authority": authority,
        "document": document,
        "candidate": candidate,
        "revision": revision,
        "run": run,
        "verifications": verifications,
        "evidence": evidence_records,
        "confidence": confidence,
        "case": review_case,
    }


def _field_item(review_case: dict, field_path: str | None = None) -> dict:
    items = [item for item in review_case["items"] if item["scope"] == "FIELD"]
    if field_path is None:
        assert len(items) == 1
        return items[0]
    return next(item for item in items if item["field_path_snapshot"] == field_path)


def _resolve_all(
    client: TestClient,
    review_case: dict,
    decisions: dict[str, tuple[str, dict]],
) -> dict:
    start_review_case(client, review_case["id"])
    for item in review_case["items"]:
        key = item["field_path_snapshot"] or "REVISION"
        decision, overrides = decisions.get(key, ("APPROVE_AS_IS", {}))
        decide_review_item(client, item["id"], decision, **overrides)
    return client.get(f"/api/v1/review-cases/{review_case['id']}").json()


def test_queue_generation_snapshots_items_filters_and_idempotency(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = build_review_graph(client, suffix="QUEUE")
    confidence = graph["confidence"]
    review_case = graph["case"]
    assert review_case is not None

    monkeypatch.setenv("AJI_CONFIDENCE_CRITICAL_THRESHOLD", "99")
    monkeypatch.setenv("AJI_CONFIDENCE_REVISION_THRESHOLD", "99")
    get_settings.cache_clear()
    try:
        replay = client.post(
            "/api/v1/review-cases",
            json={"revision_confidence_assessment_id": confidence["id"]},
        )
    finally:
        get_settings.cache_clear()
    retrieved = client.get(f"/api/v1/review-cases/{review_case['id']}")
    filtered = client.get(
        "/api/v1/review-cases",
        params={
            "status": "QUEUED",
            "priority": review_case["priority"],
            "candidate_revision_id": graph["revision"]["id"],
            "verification_run_id": graph["run"]["id"],
        },
    )

    assert replay.status_code == 200
    assert replay.json()["id"] == review_case["id"]
    assert retrieved.status_code == 200
    assert [item["id"] for item in filtered.json()] == [review_case["id"]]
    assert review_case["status"] == "QUEUED"
    assert review_case["priority"] == confidence["review_priority"]
    assert review_case["policy_version"] == confidence["policy_version"]
    assert review_case["revision_score_snapshot"] == confidence["score"]
    assert review_case["revision_review_reason_codes_snapshot"] == confidence["review_reason_codes"]
    assert review_case["component_breakdown_snapshot"] == confidence["component_breakdown"]
    assert {item["scope"] for item in review_case["items"]} == {
        "FIELD",
        "REVISION",
    }
    assert db_session.scalar(select(func.count(ReviewCase.id))) == 1
    assert db_session.scalar(select(func.count(ReviewItem.id))) == 2


def test_non_review_confidence_and_unknown_assessment_rejected(
    client: TestClient,
) -> None:
    graph = build_review_graph(
        client,
        suffix="SAFE",
        fields=[
            {
                "field_path": "recruitment_name",
                "value_type": "STRING",
                "value": "Safe recruitment",
            }
        ],
        modes={"recruitment_name": "auth_support"},
        create_case=False,
    )
    assert graph["confidence"]["review_required"] is False

    rejected = client.post(
        "/api/v1/review-cases",
        json={"revision_confidence_assessment_id": graph["confidence"]["id"]},
    )
    unknown = client.post(
        "/api/v1/review-cases",
        json={"revision_confidence_assessment_id": str(uuid4())},
    )

    assert rejected.status_code == 409
    assert unknown.status_code == 404


def test_queue_order_critical_high_normal_then_oldest(
    client: TestClient, db_session: Session
) -> None:
    normal_old = build_review_graph(
        client,
        suffix="ORDER_NORMAL_OLD",
        fields=[{"field_path": "description.one", "value_type": "STRING", "value": "one"}],
    )["case"]
    critical = build_review_graph(
        client,
        suffix="ORDER_CRITICAL",
        modes={"application.end_date": "auth_conflict"},
    )["case"]
    high = build_review_graph(
        client,
        suffix="ORDER_HIGH",
        modes={"application.end_date": "secondary_support"},
    )["case"]
    normal_new = build_review_graph(
        client,
        suffix="ORDER_NORMAL_NEW",
        fields=[{"field_path": "description.two", "value_type": "STRING", "value": "two"}],
    )["case"]
    assert all([normal_old, critical, high, normal_new])
    old_row = db_session.get(ReviewCase, UUID(normal_old["id"]))
    new_row = db_session.get(ReviewCase, UUID(normal_new["id"]))
    assert old_row is not None and new_row is not None
    old_row.opened_at = datetime.now(UTC) - timedelta(days=2)
    new_row.opened_at = datetime.now(UTC) - timedelta(days=1)
    db_session.commit()

    ordered = client.get("/api/v1/review-cases").json()

    assert [item["priority"] for item in ordered] == [
        "CRITICAL",
        "HIGH",
        "NORMAL",
        "NORMAL",
    ]
    assert [item["id"] for item in ordered[-2:]] == [
        normal_old["id"],
        normal_new["id"],
    ]


def test_case_lifecycle_premature_resolution_cancel_and_terminal_behavior(
    client: TestClient,
) -> None:
    first = build_review_graph(client, suffix="LIFECYCLE")["case"]
    assert first is not None
    queued_resolve = client.post(f"/api/v1/review-cases/{first['id']}/resolve")
    started = start_review_case(client, first["id"])
    second_start = client.post(f"/api/v1/review-cases/{first['id']}/start")
    premature = client.post(f"/api/v1/review-cases/{first['id']}/resolve")
    cancelled = client.post(f"/api/v1/review-cases/{first['id']}/cancel")
    replay_cancel = client.post(f"/api/v1/review-cases/{first['id']}/cancel")
    decision_after_cancel = client.post(
        f"/api/v1/review-items/{first['items'][0]['id']}/decision",
        json={"decision": "APPROVE_AS_IS", "reviewer_identifier": "reviewer"},
    )

    assert queued_resolve.status_code == 409
    assert started["status"] == "IN_REVIEW" and started["started_at"]
    assert second_start.status_code == 409
    assert premature.status_code == 409
    assert cancelled.status_code == replay_cancel.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["resolved_at"] == replay_cancel.json()["resolved_at"]
    assert decision_after_cancel.status_code == 409


def test_approve_as_is_rules_and_automatic_resolution(client: TestClient) -> None:
    review_case = build_review_graph(client, suffix="APPROVE")["case"]
    assert review_case is not None
    start_review_case(client, review_case["id"])
    field_item = _field_item(review_case)
    invalid_corrected = client.post(
        f"/api/v1/review-items/{field_item['id']}/decision",
        json={
            "decision": "APPROVE_AS_IS",
            "reviewer_identifier": "reviewer",
            "corrected_value_type": "DATE",
            "corrected_value": "2026-10-27",
        },
    )
    assert invalid_corrected.status_code == 422

    for item in review_case["items"]:
        decision = decide_review_item(client, item["id"], "APPROVE_AS_IS")
        assert decision["reviewer_identifier"] == "reviewer@example.test"
        assert decision["decided_at"]
    resolved = client.get(f"/api/v1/review-cases/{review_case['id']}").json()
    resolved_at = resolved["resolved_at"]
    replay_resolution = client.post(f"/api/v1/review-cases/{review_case['id']}/resolve")
    cancel_resolved = client.post(f"/api/v1/review-cases/{review_case['id']}/cancel")

    assert resolved["status"] == "RESOLVED"
    assert resolved["outcome"] == "APPROVED"
    assert replay_resolution.status_code == 200
    assert replay_resolution.json()["resolved_at"] == resolved_at
    assert cancel_resolved.status_code == 409


def test_corrected_value_validation_normalization_and_revision_restriction(
    client: TestClient,
) -> None:
    review_case = build_review_graph(
        client,
        suffix="DECIMAL",
        fields=[{"field_path": "application.fee", "value_type": "DECIMAL", "value": "100"}],
    )["case"]
    assert review_case is not None
    start_review_case(client, review_case["id"])
    item = _field_item(review_case)

    same = client.post(
        f"/api/v1/review-items/{item['id']}/decision",
        json={
            "decision": "CORRECT_AND_APPROVE",
            "reviewer_identifier": "reviewer",
            "decision_note": "Same value.",
            "corrected_value_type": "DECIMAL",
            "corrected_value": "100.00",
        },
    )
    wrong_type = client.post(
        f"/api/v1/review-items/{item['id']}/decision",
        json={
            "decision": "CORRECT_AND_APPROVE",
            "reviewer_identifier": "reviewer",
            "decision_note": "Wrong type.",
            "corrected_value_type": "STRING",
            "corrected_value": "120.500",
        },
    )
    accepted = client.post(
        f"/api/v1/review-items/{item['id']}/decision",
        json={
            "decision": "CORRECT_AND_APPROVE",
            "reviewer_identifier": " reviewer ",
            "decision_note": " Correct fee. ",
            "corrected_value_type": "DECIMAL",
            "corrected_value": "120.5000",
        },
    )
    revision_item = next(
        candidate for candidate in review_case["items"] if candidate["scope"] == "REVISION"
    )
    revision_correction = client.post(
        f"/api/v1/review-items/{revision_item['id']}/decision",
        json={
            "decision": "CORRECT_AND_APPROVE",
            "reviewer_identifier": "reviewer",
            "decision_note": "Cannot correct revision.",
            "corrected_value_type": "DECIMAL",
            "corrected_value": "200",
        },
    )

    assert same.status_code == wrong_type.status_code == 409
    assert accepted.status_code == 201
    assert accepted.json()["corrected_value"] == "120.5"
    assert accepted.json()["reviewer_identifier"] == "reviewer"
    assert accepted.json()["decision_note"] == "Correct fee."
    assert revision_correction.status_code == 409


@pytest.mark.parametrize("decision", ["REJECT", "REQUEST_REVERIFICATION"])
def test_notes_and_reviewer_are_required(client: TestClient, decision: str) -> None:
    review_case = build_review_graph(client, suffix=f"REQUIRED_{decision}")["case"]
    assert review_case is not None
    start_review_case(client, review_case["id"])
    item = _field_item(review_case)

    no_note = client.post(
        f"/api/v1/review-items/{item['id']}/decision",
        json={"decision": decision, "reviewer_identifier": "reviewer"},
    )
    blank_reviewer = client.post(
        f"/api/v1/review-items/{item['id']}/decision",
        json={
            "decision": decision,
            "reviewer_identifier": "   ",
            "decision_note": "Required note.",
        },
    )

    assert no_note.status_code == blank_reviewer.status_code == 422


@pytest.mark.parametrize(
    ("suffix", "decisions", "expected"),
    [
        ("OUTCOME_APPROVED", {}, "APPROVED"),
        (
            "OUTCOME_CORRECTED",
            {
                "eligibility.minimum_age": (
                    "CORRECT_AND_APPROVE",
                    {
                        "decision_note": "Correct age.",
                        "corrected_value_type": "INTEGER",
                        "corrected_value": 22,
                    },
                )
            },
            "APPROVED_WITH_CORRECTIONS",
        ),
        (
            "OUTCOME_REJECTED",
            {
                "eligibility.minimum_age": (
                    "REJECT",
                    {"decision_note": "Reject field."},
                )
            },
            "REJECTED",
        ),
        (
            "OUTCOME_REVERIFY",
            {
                "eligibility.minimum_age": (
                    "REJECT",
                    {"decision_note": "Reject field."},
                ),
                "vacancies.total": (
                    "REQUEST_REVERIFICATION",
                    {"decision_note": "Check source again."},
                ),
            },
            "REVERIFICATION_REQUESTED",
        ),
    ],
)
def test_case_outcome_precedence_and_projection_safety(
    client: TestClient,
    suffix: str,
    decisions: dict[str, tuple[str, dict]],
    expected: str,
) -> None:
    fields = [
        {"field_path": "eligibility.minimum_age", "value_type": "INTEGER", "value": 21},
        {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 10},
    ]
    review_case = build_review_graph(client, suffix=suffix, fields=fields)["case"]
    assert review_case is not None

    resolved = _resolve_all(client, review_case, decisions)
    projection = client.get(f"/api/v1/review-cases/{review_case['id']}/approved-projection")

    assert resolved["outcome"] == expected
    assert projection.status_code == 200
    expected_eligible = expected in {"APPROVED", "APPROVED_WITH_CORRECTIONS"}
    assert projection.json()["master_eligible"] is expected_eligible
    if not expected_eligible:
        assert all(item["approved"] is False for item in projection.json()["fields"])
        assert all(item["effective_value"] is None for item in projection.json()["fields"])


def test_critical_deadline_correction_projection_and_historical_immutability(
    client: TestClient,
) -> None:
    fields = [
        {"field_path": "application.end_date", "value_type": "DATE", "value": "2026-10-20"},
        {"field_path": "recruitment_name", "value_type": "STRING", "value": "Recruitment"},
    ]
    graph = build_review_graph(
        client,
        suffix="CRITICAL_CORRECTION",
        fields=fields,
        modes={
            "application.end_date": "auth_support_secondary_conflict",
            "recruitment_name": "auth_support",
        },
    )
    review_case = graph["case"]
    assert review_case is not None
    assert review_case["revision_score_snapshot"] == 87
    assert len(review_case["items"]) == 1
    deadline_item = _field_item(review_case, "application.end_date")
    assert deadline_item["confidence_score_snapshot"] == 85

    revision_before = client.get(f"/api/v1/candidate-revisions/{graph['revision']['id']}").json()
    verification_before = client.get(
        f"/api/v1/field-verifications/{deadline_item['field_verification_id']}"
    ).json()
    confidence_before = client.get(
        f"/api/v1/field-verifications/{deadline_item['field_verification_id']}/confidence"
    ).json()
    evidence_before = [
        client.get(f"/api/v1/evidence/{item['id']}").json() for item in graph["evidence"]
    ]

    start_review_case(client, review_case["id"])
    payload = {
        "decision": "CORRECT_AND_APPROVE",
        "reviewer_identifier": "deadline-reviewer",
        "decision_note": "Authoritative corrigendum extends the deadline.",
        "corrected_value_type": "DATE",
        "corrected_value": "2026-10-27",
        "evidence_note": "Reviewed the captured official notice.",
    }
    decision = client.post(f"/api/v1/review-items/{deadline_item['id']}/decision", json=payload)
    replay = client.post(f"/api/v1/review-items/{deadline_item['id']}/decision", json=payload)
    changed = client.post(
        f"/api/v1/review-items/{deadline_item['id']}/decision",
        json={**payload, "corrected_value": "2026-10-28"},
    )
    resolved = client.get(f"/api/v1/review-cases/{review_case['id']}").json()
    projection = client.get(f"/api/v1/review-cases/{review_case['id']}/approved-projection").json()

    assert decision.status_code == 201 and replay.status_code == 200
    assert replay.json()["id"] == decision.json()["id"]
    assert changed.status_code == 409
    assert decision.json()["original_value_snapshot"] == "2026-10-20"
    assert decision.json()["corrected_value"] == "2026-10-27"
    assert resolved["outcome"] == "APPROVED_WITH_CORRECTIONS"
    by_path = {item["field_path"]: item for item in projection["fields"]}
    assert projection["master_eligible"] is True
    assert by_path["application.end_date"]["original_value"] == "2026-10-20"
    assert by_path["application.end_date"]["effective_value"] == "2026-10-27"
    assert by_path["application.end_date"]["corrected"] is True
    assert by_path["application.end_date"]["review_decision_id"] == decision.json()["id"]
    assert by_path["recruitment_name"]["effective_value"] == "Recruitment"
    assert by_path["recruitment_name"]["corrected"] is False
    assert (
        client.get(f"/api/v1/candidate-revisions/{graph['revision']['id']}").json()
        == revision_before
    )
    assert (
        client.get(f"/api/v1/field-verifications/{deadline_item['field_verification_id']}").json()
        == verification_before
    )
    assert (
        client.get(
            f"/api/v1/field-verifications/{deadline_item['field_verification_id']}/confidence"
        ).json()
        == confidence_before
    )
    assert [
        client.get(f"/api/v1/evidence/{item['id']}").json() for item in graph["evidence"]
    ] == evidence_before


def test_projection_requires_resolved_case_and_unknown_resources(
    client: TestClient,
) -> None:
    review_case = build_review_graph(client, suffix="PROJECTION_PENDING")["case"]
    assert review_case is not None

    pending = client.get(f"/api/v1/review-cases/{review_case['id']}/approved-projection")
    missing_case = client.get(f"/api/v1/review-cases/{uuid4()}")
    missing_item = client.get(f"/api/v1/review-items/{uuid4()}")

    assert pending.status_code == 409
    assert missing_case.status_code == missing_item.status_code == 404


@pytest.mark.parametrize("target", ["field", "revision"])
def test_confidence_integrity_mismatch_blocks_queue(
    client: TestClient, db_session: Session, target: str
) -> None:
    graph = build_review_graph(client, suffix="INTEGRITY", create_case=False)
    if target == "field":
        field_assessment_id = graph["confidence"]["field_assessments"][0]["id"]
        assessment = db_session.get(FieldConfidenceAssessment, UUID(field_assessment_id))
        assert assessment is not None and assessment.score is not None
        assessment.score += 1
    else:
        assessment = db_session.get(RevisionConfidenceAssessment, UUID(graph["confidence"]["id"]))
        assert assessment is not None
        assessment.review_reason_codes = ["SOURCE_CONFLICT"]
    db_session.commit()

    response = client.post(
        "/api/v1/review-cases",
        json={"revision_confidence_assessment_id": graph["confidence"]["id"]},
    )

    assert response.status_code == 409
    assert "integrity" in response.json()["detail"]


def test_database_uniqueness_for_cases_items_and_decisions(
    client: TestClient, db_session: Session
) -> None:
    review_case = build_review_graph(client, suffix="DATABASE_UNIQUE")["case"]
    assert review_case is not None
    start_review_case(client, review_case["id"])
    first_item = review_case["items"][0]
    decide_review_item(client, first_item["id"], "APPROVE_AS_IS")

    assert db_session.scalar(select(func.count(ReviewCase.id))) == 1
    assert db_session.scalar(select(func.count(ReviewItem.id))) == len(review_case["items"])
    assert db_session.scalar(select(func.count(ReviewDecision.id))) == 1
