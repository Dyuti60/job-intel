import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.candidates import RecruitmentCandidateRevision
from tests.factories import (
    create_candidate,
    create_discovery_source,
    create_field_verification,
    create_ready_candidate_revision,
    create_revision,
    create_run,
    create_verification_run,
    observe_document,
    start_verification_run,
)


def test_create_run_captures_revision_snapshot_and_field_total(
    client: TestClient,
) -> None:
    _, _, _, revision = create_ready_candidate_revision(client)

    run = create_verification_run(client, revision["id"])

    assert run["candidate_revision_id"] == revision["id"]
    assert run["candidate_revision_hash_snapshot"] == revision["revision_hash"]
    assert run["status"] == "PENDING"
    assert run["started_at"] is None
    assert run["fields_total"] == len(revision["fields"])
    assert run["fields_confirmed"] == 0


def test_draft_and_discarded_candidates_are_rejected(client: TestClient) -> None:
    authority, endpoint = create_discovery_source(client)
    discovery_run = create_run(client, endpoint["id"])
    document = observe_document(client, discovery_run["id"])["document"]
    draft = create_candidate(client, authority["id"])
    draft_revision = create_revision(client, draft["id"], document["id"])

    draft_response = client.post(
        "/api/v1/verification-runs",
        json={"candidate_revision_id": draft_revision["id"], "trigger_type": "MANUAL"},
    )
    discarded_response = client.patch(
        f"/api/v1/recruitment-candidates/{draft['id']}",
        json={"status": "DISCARDED"},
    )
    assert discarded_response.status_code == 200
    discarded_run = client.post(
        "/api/v1/verification-runs",
        json={"candidate_revision_id": draft_revision["id"], "trigger_type": "MANUAL"},
    )

    assert draft_response.status_code == 409
    assert "not ready" in draft_response.json()["detail"]
    assert discarded_run.status_code == 409
    assert "Discarded" in discarded_run.json()["detail"]


def test_unknown_revision_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/verification-runs",
        json={"candidate_revision_id": str(uuid.uuid4()), "trigger_type": "MANUAL"},
    )

    assert response.status_code == 404


def test_retrieve_list_and_filter_runs(client: TestClient) -> None:
    _, _, candidate, revision = create_ready_candidate_revision(client)
    manual = create_verification_run(client, revision["id"])
    retry = create_verification_run(client, revision["id"], "RETRY")
    start_verification_run(client, manual["id"])

    retrieved = client.get(f"/api/v1/verification-runs/{manual['id']}")
    by_revision = client.get(
        "/api/v1/verification-runs",
        params={"candidate_revision_id": revision["id"]},
    )
    by_candidate = client.get(
        "/api/v1/verification-runs", params={"candidate_id": candidate["id"]}
    )
    by_status = client.get("/api/v1/verification-runs?status=RUNNING")
    by_trigger = client.get("/api/v1/verification-runs?trigger_type=RETRY")

    assert retrieved.status_code == 200
    assert retrieved.json()["status"] == "RUNNING"
    assert {item["id"] for item in by_revision.json()} == {manual["id"], retry["id"]}
    assert {item["id"] for item in by_candidate.json()} == {manual["id"], retry["id"]}
    assert [item["id"] for item in by_status.json()] == [manual["id"]]
    assert [item["id"] for item in by_trigger.json()] == [retry["id"]]


def test_run_start_lifecycle_and_revision_snapshot_guard(
    client: TestClient, db_session: Session
) -> None:
    _, _, _, revision = create_ready_candidate_revision(client)
    run = create_verification_run(client, revision["id"])

    started = start_verification_run(client, run["id"])
    repeated = client.post(f"/api/v1/verification-runs/{run['id']}/start")

    assert started["status"] == "RUNNING"
    assert started["started_at"] is not None
    assert repeated.status_code == 409

    second_run = create_verification_run(client, revision["id"])
    persisted = db_session.get(
        RecruitmentCandidateRevision, uuid.UUID(revision["id"])
    )
    assert persisted is not None
    persisted.revision_hash = "f" * 64
    db_session.commit()

    mismatch = client.post(f"/api/v1/verification-runs/{second_run['id']}/start")
    assert mismatch.status_code == 409
    assert "snapshot mismatch" in mismatch.json()["detail"]


def test_failed_run_retains_error_and_is_terminal(client: TestClient) -> None:
    _, _, _, revision = create_ready_candidate_revision(client)
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])

    failed = client.post(
        f"/api/v1/verification-runs/{run['id']}/complete",
        json={
            "status": "FAILED",
            "error_code": "EXECUTION_ERROR",
            "error_message": "Controlled verification failed.",
        },
    )
    repeated = client.post(
        f"/api/v1/verification-runs/{run['id']}/complete",
        json={"status": "FAILED"},
    )
    field_attempt = client.post(
        f"/api/v1/verification-runs/{run['id']}/fields/{revision['fields'][0]['id']}"
    )

    assert failed.status_code == 200
    assert failed.json()["completed_at"] is not None
    assert failed.json()["error_code"] == "EXECUTION_ERROR"
    assert repeated.status_code == 409
    assert field_attempt.status_code == 409


def test_field_must_belong_to_exact_target_revision(client: TestClient) -> None:
    authority, document, candidate, first_revision = create_ready_candidate_revision(client)
    second_revision = create_revision(
        client,
        candidate["id"],
        document["id"],
        fields=[
            {
                "field_path": "vacancies.total",
                "value_type": "INTEGER",
                "value": 99,
            }
        ],
    )
    other_candidate = create_candidate(
        client,
        authority["id"],
        candidate_key="OTHER_CANDIDATE",
        display_name="Other candidate",
    )
    other_revision = create_revision(client, other_candidate["id"], document["id"])
    _, _, _, other_authority_revision = create_ready_candidate_revision(
        client,
        authority_overrides={
            "code": "OTHER_AUTHORITY",
            "name": "Other Authority",
            "official_website_url": "https://other-authority.example.gov.in",
        },
        endpoint_overrides={
            "canonical_url": "https://other-authority.example.gov.in/notices"
        },
    )
    run = create_verification_run(client, first_revision["id"])
    start_verification_run(client, run["id"])

    accepted = create_field_verification(
        client, run["id"], first_revision["fields"][0]["id"]
    )
    replay = client.post(
        f"/api/v1/verification-runs/{run['id']}/fields/"
        f"{first_revision['fields'][0]['id']}"
    )
    retrieved = client.get(f"/api/v1/field-verifications/{accepted['id']}")
    listed = client.get(f"/api/v1/verification-runs/{run['id']}/fields")
    other_revision_response = client.post(
        f"/api/v1/verification-runs/{run['id']}/fields/"
        f"{second_revision['fields'][0]['id']}"
    )
    other_candidate_response = client.post(
        f"/api/v1/verification-runs/{run['id']}/fields/"
        f"{other_revision['fields'][0]['id']}"
    )
    other_authority_response = client.post(
        f"/api/v1/verification-runs/{run['id']}/fields/"
        f"{other_authority_revision['fields'][0]['id']}"
    )

    assert accepted["candidate_field_path_snapshot"] == "recruitment_name"
    assert accepted["candidate_field_value_snapshot"] == "Combined Competitive Recruitment"
    assert accepted["candidate_field_type_snapshot"] == "STRING"
    assert replay.status_code == 200
    assert replay.json()["id"] == accepted["id"]
    assert retrieved.json() == accepted
    assert [item["id"] for item in listed.json()] == [accepted["id"]]
    assert other_revision_response.status_code == 409
    assert other_candidate_response.status_code == 409
    assert other_authority_response.status_code == 409
