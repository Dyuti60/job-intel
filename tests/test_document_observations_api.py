import hashlib
import uuid

from fastapi.testclient import TestClient

from tests.factories import (
    create_discovery_source,
    create_run,
    document_payload,
    observe_document,
)


def test_first_document_observation_is_new_and_hashes_content(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])

    response = client.post(
        f"/api/v1/discovery-runs/{run['id']}/documents",
        json=document_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    expected_hash = hashlib.sha256(b"controlled test document").hexdigest()
    assert body["classification"] == "NEW"
    assert body["document"]["content_hash"] == expected_hash
    assert body["document"]["content_length"] == len(b"controlled test document")
    assert body["document"]["first_discovery_run_id"] == run["id"]
    assert body["observation"]["discovery_run_id"] == run["id"]
    assert body["observation"]["source_document_id"] == body["document"]["id"]


def test_same_url_and_content_across_runs_is_unchanged(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    first_run = create_run(client, endpoint["id"])
    first = observe_document(client, first_run["id"])
    second_run = create_run(client, endpoint["id"], trigger_type="SCHEDULED")

    second = observe_document(client, second_run["id"])

    assert second["classification"] == "UNCHANGED"
    assert second["document"]["id"] == first["document"]["id"]
    assert second["document"]["first_seen_at"] == first["document"]["first_seen_at"]
    assert second["document"]["first_discovery_run_id"] == first_run["id"]
    assert second["document"]["latest_discovery_run_id"] == second_run["id"]
    assert second["document"]["last_seen_at"] >= first["document"]["last_seen_at"]


def test_changed_content_creates_new_version_and_preserves_previous(
    client: TestClient,
) -> None:
    _, endpoint = create_discovery_source(client)
    first_run = create_run(client, endpoint["id"])
    first = observe_document(client, first_run["id"], content_text="version one")
    second_run = create_run(client, endpoint["id"])

    changed = observe_document(client, second_run["id"], content_text="version two")

    assert changed["classification"] == "CHANGED"
    assert changed["document"]["id"] != first["document"]["id"]
    assert changed["document"]["content_hash"] != first["document"]["content_hash"]
    previous = client.get(f"/api/v1/source-documents/{first['document']['id']}")
    assert previous.status_code == 200
    assert previous.json()["content_hash"] == hashlib.sha256(b"version one").hexdigest()
    versions = client.get(
        "/api/v1/source-documents",
        params={"normalized_document_url": first["document"]["normalized_document_url"]},
    )
    assert versions.status_code == 200
    assert {item["id"] for item in versions.json()} == {
        first["document"]["id"],
        changed["document"]["id"],
    }


def test_url_normalization_prevents_trivial_duplicate_versions(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    first_run = create_run(client, endpoint["id"])
    first = observe_document(
        client,
        first_run["id"],
        document_url="HTTPS://JOBS.EXAMPLE.GOV.IN:443/notices/notice-1.pdf#download",
    )
    second_run = create_run(client, endpoint["id"])

    second = observe_document(
        client,
        second_run["id"],
        document_url="https://jobs.example.gov.in/notices/notice-1.pdf",
    )

    assert second["classification"] == "UNCHANGED"
    assert second["document"]["id"] == first["document"]["id"]
    assert first["document"]["document_url"].startswith("HTTPS://")
    assert first["document"]["normalized_document_url"] == (
        "https://jobs.example.gov.in/notices/notice-1.pdf"
    )


def test_different_urls_with_identical_content_remain_distinct(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    first = observe_document(client, run["id"])

    second = observe_document(
        client,
        run["id"],
        document_url="https://jobs.example.gov.in/archive/notice-1.pdf",
    )

    assert second["classification"] == "NEW"
    assert second["document"]["id"] != first["document"]["id"]
    assert second["document"]["content_hash"] == first["document"]["content_hash"]


def test_invalid_document_url_and_hash_are_rejected(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])

    invalid_url = client.post(
        f"/api/v1/discovery-runs/{run['id']}/documents",
        json=document_payload(document_url="ftp://example.gov.in/file.pdf"),
    )
    invalid_hash = client.post(
        f"/api/v1/discovery-runs/{run['id']}/documents",
        json=document_payload(content_text=None, content_hash="not-a-sha256"),
    )

    assert invalid_url.status_code == 422
    assert invalid_hash.status_code == 422


def test_external_sha256_is_canonicalized(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    uppercase_hash = hashlib.sha256(b"hash-only content").hexdigest().upper()

    observed = observe_document(
        client,
        run["id"],
        content_text=None,
        content_hash=uppercase_hash,
        content_length=17,
    )

    assert observed["document"]["content_hash"] == uppercase_hash.lower()
    assert observed["document"]["content_length"] == 17


def test_observation_history_is_retained_across_runs(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    first_run = create_run(client, endpoint["id"])
    first = observe_document(client, first_run["id"])
    second_run = create_run(client, endpoint["id"])
    second = observe_document(client, second_run["id"])

    first_history = client.get(f"/api/v1/discovery-runs/{first_run['id']}/documents")
    second_history = client.get(f"/api/v1/discovery-runs/{second_run['id']}/documents")

    assert first_history.status_code == 200
    assert second_history.status_code == 200
    assert first_history.json()[0]["observation_status"] == "NEW"
    assert second_history.json()[0]["observation_status"] == "UNCHANGED"
    assert first_history.json()[0]["source_document_id"] == first["document"]["id"]
    assert second_history.json()[0]["source_document_id"] == second["document"]["id"]


def test_run_counters_are_service_managed_and_idempotent(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    first = observe_document(client, run["id"], content_text="first")
    repeated = observe_document(client, run["id"], content_text="first")
    changed = observe_document(client, run["id"], content_text="second")

    current_run = client.get(f"/api/v1/discovery-runs/{run['id']}").json()

    assert repeated["observation"]["id"] == first["observation"]["id"]
    assert changed["classification"] == "CHANGED"
    assert current_run["documents_discovered"] == 2
    assert current_run["documents_new"] == 1
    assert current_run["documents_changed"] == 1
    assert current_run["documents_unchanged"] == 0


def test_completed_run_rejects_new_observations(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    completion = client.post(
        f"/api/v1/discovery-runs/{run['id']}/complete",
        json={"status": "SUCCEEDED"},
    )
    assert completion.status_code == 200

    response = client.post(
        f"/api/v1/discovery-runs/{run['id']}/documents",
        json=document_payload(),
    )

    assert response.status_code == 409
    assert "SUCCEEDED status" in response.json()["detail"]


def test_source_document_filters_and_unknown_id(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    observed = observe_document(client, run["id"])

    by_endpoint = client.get(
        "/api/v1/source-documents",
        params={"source_endpoint_id": endpoint["id"]},
    )
    by_type = client.get("/api/v1/source-documents?document_type=PDF")
    by_status = client.get("/api/v1/source-documents?status=ACTIVE")
    missing = client.get(f"/api/v1/source-documents/{uuid.uuid4()}")

    assert [item["id"] for item in by_endpoint.json()] == [observed["document"]["id"]]
    assert [item["id"] for item in by_type.json()] == [observed["document"]["id"]]
    assert [item["id"] for item in by_status.json()] == [observed["document"]["id"]]
    assert missing.status_code == 404
