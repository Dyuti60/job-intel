import uuid

import pytest
from fastapi.testclient import TestClient

from tests.factories import create_discovery_source, create_run


def test_create_run_for_eligible_source(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)

    response = client.post(
        "/api/v1/discovery-runs",
        json={"source_endpoint_id": endpoint["id"], "trigger_type": "MANUAL"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source_endpoint_id"] == endpoint["id"]
    assert body["status"] == "RUNNING"
    assert body["started_at"]
    assert body["completed_at"] is None
    assert body["documents_discovered"] == 0


def test_unknown_source_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/discovery-runs",
        json={"source_endpoint_id": str(uuid.uuid4()), "trigger_type": "MANUAL"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Source endpoint not found"


def test_inactive_authority_is_rejected(client: TestClient) -> None:
    _, endpoint = create_discovery_source(
        client,
        authority_overrides={"status": "INACTIVE"},
    )

    response = client.post(
        "/api/v1/discovery-runs",
        json={"source_endpoint_id": endpoint["id"], "trigger_type": "MANUAL"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Recruiting authority is not active"


@pytest.mark.parametrize("endpoint_status", ["INACTIVE", "DISABLED"])
def test_inactive_or_disabled_endpoint_is_rejected(
    client: TestClient, endpoint_status: str
) -> None:
    _, endpoint = create_discovery_source(
        client,
        endpoint_overrides={"status": endpoint_status},
    )

    response = client.post(
        "/api/v1/discovery-runs",
        json={"source_endpoint_id": endpoint["id"], "trigger_type": "MANUAL"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Source endpoint is not active"


def test_discovery_disabled_endpoint_is_rejected(client: TestClient) -> None:
    _, endpoint = create_discovery_source(
        client,
        endpoint_overrides={"discovery_enabled": False},
    )

    response = client.post(
        "/api/v1/discovery-runs",
        json={"source_endpoint_id": endpoint["id"], "trigger_type": "MANUAL"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Discovery is disabled for this source endpoint"


def test_retrieve_run(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])

    response = client.get(f"/api/v1/discovery-runs/{run['id']}")

    assert response.status_code == 200
    assert response.json() == run


def test_list_and_filter_runs(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    manual_run = create_run(client, endpoint["id"])
    retry_run = create_run(client, endpoint["id"], trigger_type="RETRY")
    completed = client.post(
        f"/api/v1/discovery-runs/{manual_run['id']}/complete",
        json={"status": "SUCCEEDED"},
    )
    assert completed.status_code == 200

    by_status = client.get("/api/v1/discovery-runs?status=SUCCEEDED")
    by_trigger = client.get("/api/v1/discovery-runs?trigger_type=RETRY")
    by_endpoint = client.get(
        "/api/v1/discovery-runs",
        params={"source_endpoint_id": endpoint["id"]},
    )

    assert [item["id"] for item in by_status.json()] == [manual_run["id"]]
    assert [item["id"] for item in by_trigger.json()] == [retry_run["id"]]
    assert {item["id"] for item in by_endpoint.json()} == {
        manual_run["id"],
        retry_run["id"],
    }


def test_complete_successful_run(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])

    response = client.post(
        f"/api/v1/discovery-runs/{run['id']}/complete",
        json={"status": "SUCCEEDED"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["completed_at"] is not None
    assert body["error_code"] is None


def test_fail_run_retains_error_details(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"], trigger_type="RETRY")

    response = client.post(
        f"/api/v1/discovery-runs/{run['id']}/complete",
        json={
            "status": "FAILED",
            "error_code": "FETCH_TIMEOUT",
            "error_message": "The controlled execution timed out.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["error_code"] == "FETCH_TIMEOUT"
    assert body["error_message"] == "The controlled execution timed out."


def test_invalid_lifecycle_transition_is_rejected(client: TestClient) -> None:
    _, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    first_completion = client.post(
        f"/api/v1/discovery-runs/{run['id']}/complete",
        json={"status": "SUCCEEDED"},
    )
    assert first_completion.status_code == 200

    response = client.post(
        f"/api/v1/discovery-runs/{run['id']}/complete",
        json={"status": "FAILED", "error_code": "LATE_FAILURE"},
    )

    assert response.status_code == 409
    assert "SUCCEEDED status" in response.json()["detail"]
