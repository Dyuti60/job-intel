import uuid

from fastapi.testclient import TestClient

from tests.factories import (
    candidate_payload,
    create_authority,
    create_candidate,
    create_discovery_source,
    create_revision,
    create_run,
    observe_document,
)


def test_create_candidate_normalizes_key(client: TestClient) -> None:
    authority = create_authority(client)

    response = client.post(
        "/api/v1/recruitment-candidates",
        json=candidate_payload(authority["id"], candidate_key=" apsc_advt_12_2026 "),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["candidate_key"] == "APSC_ADVT_12_2026"
    assert body["status"] == "DRAFT"
    assert body["revision_count"] == 0
    assert body["latest_revision_number"] is None


def test_duplicate_candidate_is_rejected(client: TestClient) -> None:
    authority = create_authority(client)
    create_candidate(client, authority["id"])

    response = client.post(
        "/api/v1/recruitment-candidates",
        json=candidate_payload(authority["id"], display_name="Duplicate proposal"),
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_invalid_candidate_key_and_empty_name_are_rejected(client: TestClient) -> None:
    authority = create_authority(client)

    invalid_key = client.post(
        "/api/v1/recruitment-candidates",
        json=candidate_payload(authority["id"], candidate_key="invalid key!"),
    )
    empty_name = client.post(
        "/api/v1/recruitment-candidates",
        json=candidate_payload(authority["id"], display_name="   "),
    )

    assert invalid_key.status_code == 422
    assert empty_name.status_code == 422


def test_unknown_authority_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/recruitment-candidates",
        json=candidate_payload(str(uuid.uuid4())),
    )

    assert response.status_code == 404


def test_inactive_authority_is_rejected(client: TestClient) -> None:
    authority = create_authority(client, status="INACTIVE")

    response = client.post(
        "/api/v1/recruitment-candidates",
        json=candidate_payload(authority["id"]),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Recruiting authority is not active"


def test_retrieve_candidate(client: TestClient) -> None:
    authority = create_authority(client)
    candidate = create_candidate(client, authority["id"])

    response = client.get(f"/api/v1/recruitment-candidates/{candidate['id']}")

    assert response.status_code == 200
    assert response.json() == candidate


def test_list_and_filter_candidates(client: TestClient) -> None:
    first_authority = create_authority(client)
    first = create_candidate(client, first_authority["id"])
    second_authority = create_authority(
        client,
        code="SECOND_AUTHORITY",
        name="Second Authority",
        official_website_url="https://second.example.gov.in",
    )
    second = create_candidate(
        client,
        second_authority["id"],
        candidate_key="SECOND_RECRUITMENT_2026",
        display_name="Second Recruitment",
    )
    discarded = client.patch(
        f"/api/v1/recruitment-candidates/{second['id']}",
        json={"status": "DISCARDED"},
    )
    assert discarded.status_code == 200

    by_authority = client.get(
        "/api/v1/recruitment-candidates",
        params={"recruiting_authority_id": first_authority["id"]},
    )
    by_status = client.get("/api/v1/recruitment-candidates?status=DISCARDED")

    assert [item["id"] for item in by_authority.json()] == [first["id"]]
    assert [item["id"] for item in by_status.json()] == [second["id"]]


def test_draft_can_be_discarded_but_cannot_reverse(client: TestClient) -> None:
    authority = create_authority(client)
    candidate = create_candidate(client, authority["id"])

    discarded = client.patch(
        f"/api/v1/recruitment-candidates/{candidate['id']}",
        json={"status": "DISCARDED"},
    )
    reversed_transition = client.patch(
        f"/api/v1/recruitment-candidates/{candidate['id']}",
        json={"status": "DRAFT"},
    )

    assert discarded.status_code == 200
    assert discarded.json()["status"] == "DISCARDED"
    assert reversed_transition.status_code == 409


def test_draft_without_revision_cannot_be_ready(client: TestClient) -> None:
    authority = create_authority(client)
    candidate = create_candidate(client, authority["id"])

    response = client.patch(
        f"/api/v1/recruitment-candidates/{candidate['id']}",
        json={"status": "READY_FOR_VERIFICATION"},
    )

    assert response.status_code == 409
    assert "requires at least one revision" in response.json()["detail"]


def test_draft_with_revision_can_be_ready(client: TestClient) -> None:
    authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    candidate = create_candidate(client, authority["id"])
    create_revision(client, candidate["id"], document["id"])

    response = client.patch(
        f"/api/v1/recruitment-candidates/{candidate['id']}",
        json={"status": "READY_FOR_VERIFICATION"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "READY_FOR_VERIFICATION"
    assert response.json()["revision_count"] == 1
