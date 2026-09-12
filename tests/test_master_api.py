from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.candidates import CandidateField, CandidateValueType
from app.models.confidence import RevisionConfidenceAssessment
from app.models.master import (
    MasterChange,
    MasterField,
    MasterPublicationEvent,
    RecruitmentMaster,
    RecruitmentMasterRevision,
)
from app.models.review import ReviewCase
from app.services.master import MasterPublisherService, compute_projection_hash
from tests.factories import (
    add_verification_assessment,
    complete_verification_run,
    create_evidence,
    create_field_verification,
    create_ready_candidate_revision,
    create_revision,
    create_revision_confidence,
    create_run,
    create_verification_run,
    decide_review_item,
    finalize_field_verification,
    observe_document,
    start_review_case,
    start_verification_run,
)
from tests.test_review_api import _field_item, build_review_graph


def _verify_revision(client: TestClient, document: dict, revision: dict) -> dict:
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    evidence = create_evidence(
        client,
        document["id"],
        excerpt=f"Official values for {revision['id']}",
    )
    for field in revision["fields"]:
        verification = create_field_verification(client, run["id"], field["id"])
        add_verification_assessment(
            client,
            verification["id"],
            evidence["id"],
            "SUPPORTS",
            asserted_value=field["value"],
            asserted_value_type=field["value_type"],
        )
        finalize_field_verification(client, verification["id"])
    completed = complete_verification_run(client, run["id"])
    confidence = create_revision_confidence(client, run["id"])
    assert confidence["review_required"] is False
    return {"run": completed, "confidence": confidence, "evidence": evidence}


def _direct_graph(
    client: TestClient,
    suffix: str,
    fields: list[dict] | None = None,
) -> dict:
    fields = fields or [
        {"field_path": "recruitment_name", "value_type": "STRING", "value": "Recruitment"},
        {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 42},
    ]
    authority, document, candidate, revision = create_ready_candidate_revision(
        client,
        fields=fields,
        authority_overrides={
            "code": f"MASTER_{suffix}",
            "name": f"Master authority {suffix}",
            "official_website_url": f"https://master-{suffix.lower()}.gov.in",
        },
        endpoint_overrides={"canonical_url": f"https://master-{suffix.lower()}.gov.in/notices"},
    )
    verified = _verify_revision(client, document, revision)
    return {
        "authority": authority,
        "document": document,
        "candidate": candidate,
        "revision": revision,
        **verified,
    }


def _publish(client: TestClient, confidence_id: str):
    return client.post(
        "/api/v1/recruitment-master/publish",
        json={"revision_confidence_assessment_id": confidence_id},
    )


def _new_candidate_revision(
    client: TestClient,
    graph: dict,
    suffix: str,
    fields: list[dict],
) -> dict:
    discovery_run = create_run(client, graph["document"]["source_endpoint_id"])
    document = observe_document(
        client,
        discovery_run["id"],
        document_url=f"https://master-update.example.test/{suffix}.pdf",
        content_text=f"updated source {suffix}",
    )["document"]
    revision = create_revision(
        client,
        graph["candidate"]["id"],
        document["id"],
        fields=fields,
    )
    return {
        "document": document,
        "revision": revision,
        **_verify_revision(client, document, revision),
    }


def test_direct_publication_creates_master_fields_changes_and_read_apis(
    client: TestClient, db_session: Session
) -> None:
    graph = _direct_graph(client, "DIRECT")

    response = _publish(client, graph["confidence"]["id"])
    body = response.json()

    assert response.status_code == 201
    assert body["revision_created"] is True
    assert body["master_revision"]["revision_number"] == 1
    assert body["master_revision"]["publication_path"] == "VERIFIED_NO_REVIEW"
    assert body["master"]["current_revision_id"] == body["master_revision"]["id"]
    assert {field["value_origin"] for field in body["master_revision"]["fields"]} == {
        "CANDIDATE_VERIFIED"
    }
    assert all(field["review_decision_id"] is None for field in body["master_revision"]["fields"])
    assert db_session.scalar(select(func.count(MasterChange.id))) == 2
    assert {
        item["change_type"]
        for item in client.get(f"/api/v1/recruitment-master/{body['master']['id']}/changes").json()
    } == {"ADDED"}

    listed = client.get(
        "/api/v1/recruitment-master",
        params={
            "recruiting_authority_id": graph["authority"]["id"],
            "status": "ACTIVE",
            "candidate_key": graph["candidate"]["candidate_key"].lower(),
        },
    )
    detail = client.get(f"/api/v1/recruitment-master/{body['master']['id']}")
    revisions = client.get(f"/api/v1/recruitment-master/{body['master']['id']}/revisions")
    revision = client.get(f"/api/v1/recruitment-master-revisions/{body['master_revision']['id']}")
    events = client.get(f"/api/v1/recruitment-master/{body['master']['id']}/publication-events")
    assert [item["id"] for item in listed.json()] == [body["master"]["id"]]
    assert detail.status_code == revisions.status_code == revision.status_code == 200
    assert len(revisions.json()) == 1 and len(events.json()) == 1
    assert revision.json()["source_candidate_revision_id"] == graph["revision"]["id"]
    assert revision.json()["verification_run_id"] == graph["run"]["id"]
    assert revision.json()["revision_confidence_assessment_id"] == graph["confidence"]["id"]


def test_required_review_cannot_be_bypassed(client: TestClient) -> None:
    graph = build_review_graph(client, suffix="MASTER_REVIEW_MISSING", create_case=False)
    response = _publish(client, graph["confidence"]["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == "Required ReviewCase is missing"


def test_approved_review_publishes_original_value(client: TestClient) -> None:
    graph = build_review_graph(
        client,
        suffix="MASTER_APPROVED",
        modes={"application.end_date": "auth_support_secondary_conflict"},
    )
    start_review_case(client, graph["case"]["id"])
    decide_review_item(client, _field_item(graph["case"])["id"], "APPROVE_AS_IS")

    body = _publish(client, graph["confidence"]["id"]).json()

    assert body["master_revision"]["publication_path"] == "HUMAN_APPROVED"
    field = body["master_revision"]["fields"][0]
    assert field["value"] == "2026-10-20"
    assert field["value_origin"] == "HUMAN_APPROVED_AS_IS"
    assert field["review_decision_id"] is not None
    assert body["master_revision"]["review_case_id"] == graph["case"]["id"]


def test_corrected_review_end_to_end_preserves_original_and_provenance(
    client: TestClient, db_session: Session
) -> None:
    graph = build_review_graph(
        client,
        suffix="MASTER_CORRECTED",
        modes={"application.end_date": "auth_support_secondary_conflict"},
    )
    item = _field_item(graph["case"])
    start_review_case(client, graph["case"]["id"])
    decision = decide_review_item(
        client,
        item["id"],
        "CORRECT_AND_APPROVE",
        corrected_value_type="DATE",
        corrected_value="2026-10-27",
        decision_note="Authoritative correction.",
    )

    response = _publish(client, graph["confidence"]["id"])
    field = response.json()["master_revision"]["fields"][0]

    assert response.status_code == 201
    assert response.json()["master_revision"]["publication_path"] == "HUMAN_CORRECTED"
    assert field["value"] == "2026-10-27"
    assert field["source_candidate_field_id"] == graph["revision"]["fields"][0]["id"]
    assert field["review_decision_id"] == decision["id"]
    assert field["value_origin"] == "HUMAN_CORRECTED"
    original = db_session.get(CandidateField, UUID(field["source_candidate_field_id"]))
    assert original is not None and original.value == "2026-10-20"
    assert (
        graph["document"]["id"]
        == client.get(f"/api/v1/candidate-revisions/{graph['revision']['id']}").json()[
            "source_document_id"
        ]
    )


@pytest.mark.parametrize(
    ("decision", "outcome"),
    [
        ("REJECT", "REJECTED"),
        ("REQUEST_REVERIFICATION", "REVERIFICATION_REQUESTED"),
    ],
)
def test_rejected_and_reverification_reviews_cannot_publish(
    client: TestClient, decision: str, outcome: str
) -> None:
    graph = build_review_graph(client, suffix=f"MASTER_{decision}")
    start_review_case(client, graph["case"]["id"])
    for item in graph["case"]["items"]:
        decide_review_item(client, item["id"], decision)
    review_case = client.get(f"/api/v1/review-cases/{graph['case']['id']}").json()

    response = _publish(client, graph["confidence"]["id"])

    assert review_case["outcome"] == outcome
    assert response.status_code == 409
    assert f"Review outcome {outcome} is not publishable" in response.json()["detail"]


def test_same_publication_is_idempotent_without_duplicate_rows(
    client: TestClient, db_session: Session
) -> None:
    graph = _direct_graph(client, "IDEMPOTENT")
    first = _publish(client, graph["confidence"]["id"])
    replay = _publish(client, graph["confidence"]["id"])

    assert first.status_code == 201 and replay.status_code == 200
    assert replay.json()["revision_created"] is False
    assert replay.json()["master"]["id"] == first.json()["master"]["id"]
    assert replay.json()["master_revision"]["id"] == first.json()["master_revision"]["id"]
    assert replay.json()["publication_event"]["id"] == first.json()["publication_event"]["id"]
    assert db_session.scalar(select(func.count(RecruitmentMaster.id))) == 1
    assert db_session.scalar(select(func.count(RecruitmentMasterRevision.id))) == 1
    assert db_session.scalar(select(func.count(MasterField.id))) == 2
    assert db_session.scalar(select(func.count(MasterChange.id))) == 2
    assert db_session.scalar(select(func.count(MasterPublicationEvent.id))) == 1


def test_changed_projection_creates_revision_and_added_updated_removed_changes(
    client: TestClient,
) -> None:
    initial_fields = [
        {"field_path": "description.summary", "value_type": "STRING", "value": "Old"},
        {"field_path": "description.legacy", "value_type": "STRING", "value": "Remove"},
    ]
    graph = _direct_graph(client, "CHANGES", initial_fields)
    first = _publish(client, graph["confidence"]["id"]).json()
    updated = _new_candidate_revision(
        client,
        graph,
        "changes-v2",
        [
            {"field_path": "description.summary", "value_type": "STRING", "value": "New"},
            {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 100},
        ],
    )

    second_response = _publish(client, updated["confidence"]["id"])
    second = second_response.json()
    history = client.get(f"/api/v1/recruitment-master/{first['master']['id']}/revisions").json()
    changes = client.get(f"/api/v1/recruitment-master/{first['master']['id']}/changes").json()
    latest_changes = [
        item for item in changes if item["to_master_revision_id"] == second["master_revision"]["id"]
    ]

    assert second_response.status_code == 201
    assert second["master"]["id"] == first["master"]["id"]
    assert second["master_revision"]["revision_number"] == 2
    assert second["master"]["current_revision_id"] == second["master_revision"]["id"]
    assert [item["revision_number"] for item in history] == [1, 2]
    by_path = {item["field_path"]: item for item in latest_changes}
    assert by_path["description.summary"]["change_type"] == "UPDATED"
    assert by_path["description.summary"]["old_value"] == "Old"
    assert by_path["description.summary"]["new_value"] == "New"
    assert by_path["vacancies.total"]["change_type"] == "ADDED"
    assert by_path["description.legacy"]["change_type"] == "REMOVED"


def test_new_source_revision_with_identical_projection_reuses_business_revision(
    client: TestClient, db_session: Session
) -> None:
    fields = [{"field_path": "description.summary", "value_type": "STRING", "value": "Same"}]
    graph = _direct_graph(client, "REVERIFY", fields)
    first = _publish(client, graph["confidence"]["id"]).json()
    newer = _new_candidate_revision(client, graph, "same-values-new-source", deepcopy(fields))

    response = _publish(client, newer["confidence"]["id"])
    body = response.json()

    assert response.status_code == 200
    assert body["revision_created"] is False
    assert body["master_revision"]["id"] == first["master_revision"]["id"]
    assert body["publication_event"]["result"] == "UNCHANGED"
    assert body["publication_event"]["source_candidate_revision_id"] == newer["revision"]["id"]
    assert db_session.scalar(select(func.count(RecruitmentMasterRevision.id))) == 1
    assert db_session.scalar(select(func.count(MasterPublicationEvent.id))) == 2
    assert db_session.scalar(select(func.count(MasterChange.id))) == 1


def test_incomplete_verification_and_integrity_mismatch_are_rejected(
    client: TestClient, db_session: Session
) -> None:
    _, document, _, revision = create_ready_candidate_revision(
        client,
        fields=[
            {"field_path": "description.one", "value_type": "STRING", "value": "one"},
            {"field_path": "description.two", "value_type": "STRING", "value": "two"},
        ],
        authority_overrides={
            "code": "MASTER_PARTIAL",
            "official_website_url": "https://master-partial.gov.in",
        },
        endpoint_overrides={"canonical_url": "https://master-partial.gov.in/notices"},
    )
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    verification = create_field_verification(client, run["id"], revision["fields"][0]["id"])
    evidence = create_evidence(client, document["id"], excerpt="one")
    add_verification_assessment(
        client,
        verification["id"],
        evidence["id"],
        "SUPPORTS",
        asserted_value="one",
        asserted_value_type="STRING",
    )
    finalize_field_verification(client, verification["id"])
    complete_verification_run(client, run["id"], "PARTIAL")
    confidence = create_revision_confidence(client, run["id"])
    assert _publish(client, confidence["id"]).status_code == 409

    valid = _direct_graph(client, "INTEGRITY")
    row = db_session.get(RevisionConfidenceAssessment, UUID(valid["confidence"]["id"]))
    assert row is not None
    row.input_hash = "f" * 64
    db_session.commit()
    integrity = _publish(client, valid["confidence"]["id"])
    assert integrity.status_code == 409
    assert "integrity" in integrity.json()["detail"].lower()


def test_review_snapshot_mismatch_blocks_publication(
    client: TestClient, db_session: Session
) -> None:
    graph = build_review_graph(
        client,
        suffix="MASTER_REVIEW_INTEGRITY",
        modes={"application.end_date": "auth_support_secondary_conflict"},
    )
    start_review_case(client, graph["case"]["id"])
    decide_review_item(client, _field_item(graph["case"])["id"], "APPROVE_AS_IS")
    row = db_session.get(ReviewCase, UUID(graph["case"]["id"]))
    assert row is not None
    row.revision_score_snapshot = row.revision_score_snapshot - 1
    db_session.commit()

    response = _publish(client, graph["confidence"]["id"])

    assert response.status_code == 409
    assert "ReviewCase confidence snapshot" in response.json()["detail"]


def test_publish_failure_rolls_back_every_master_object(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = _direct_graph(client, "ROLLBACK")

    def fail_changes(*_args) -> None:
        raise RuntimeError("forced change failure")

    monkeypatch.setattr(MasterPublisherService, "_record_changes", fail_changes)
    with pytest.raises(RuntimeError, match="forced change failure"):
        MasterPublisherService(db_session).publish(UUID(graph["confidence"]["id"]))

    assert db_session.scalar(select(func.count(RecruitmentMaster.id))) == 0
    assert db_session.scalar(select(func.count(RecruitmentMasterRevision.id))) == 0
    assert db_session.scalar(select(func.count(MasterField.id))) == 0
    assert db_session.scalar(select(func.count(MasterChange.id))) == 0
    assert db_session.scalar(select(func.count(MasterPublicationEvent.id))) == 0


def test_unknown_master_resources_return_404(client: TestClient) -> None:
    unknown = uuid4()
    assert _publish(client, str(unknown)).status_code == 404
    assert client.get(f"/api/v1/recruitment-master/{unknown}").status_code == 404
    assert client.get(f"/api/v1/recruitment-master/{unknown}/revisions").status_code == 404
    assert client.get(f"/api/v1/recruitment-master-revisions/{unknown}").status_code == 404


def test_projection_hash_is_deterministic_and_business_content_sensitive() -> None:
    base = [
        ("a", "STRING", "value"),
        ("b", "INTEGER", 2),
    ]

    def hashed(fields, display_name="Recruitment"):
        return compute_projection_hash(
            authority_code="APSC",
            candidate_key="APSC_2026",
            display_name=display_name,
            fields=[
                (path, CandidateValueType(kind), value)
                for path, kind, value in fields
            ],
        )

    original = hashed(base)
    assert hashed(list(reversed(base))) == original
    assert hashed(deepcopy(base)) == original
    assert hashed([("a", "STRING", "changed"), base[1]]) != original
    assert hashed([("a", "JSON", "value"), base[1]]) != original
    assert hashed([*base, ("c", "BOOLEAN", True)]) != original
    assert hashed([base[0]]) != original
    assert hashed(base, display_name="Renamed Recruitment") != original
