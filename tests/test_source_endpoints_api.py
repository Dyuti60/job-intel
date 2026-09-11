import uuid

import pytest
from fastapi.testclient import TestClient

from tests.factories import create_authority, create_endpoint, endpoint_payload


def test_register_endpoint_linked_to_authority(client: TestClient) -> None:
    authority = create_authority(client)

    response = client.post(
        "/api/v1/source-endpoints",
        json=endpoint_payload(authority["id"]),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["recruiting_authority_id"] == authority["id"]
    assert body["source_class"] == "AUTHORITATIVE_OFFICIAL"
    assert body["discovery_enabled"] is True
    assert body["last_verified_at"].startswith("2026-09-12T10:00:00")


def test_retrieve_endpoint(client: TestClient) -> None:
    authority = create_authority(client)
    endpoint = create_endpoint(client, authority["id"])

    response = client.get(f"/api/v1/source-endpoints/{endpoint['id']}")

    assert response.status_code == 200
    assert response.json() == endpoint


def test_list_endpoints(client: TestClient) -> None:
    authority = create_authority(client)
    create_endpoint(client, authority["id"])
    create_endpoint(
        client,
        authority["id"],
        name="Notification archive",
        canonical_url="https://jobs.example.gov.in/notifications",
        source_type="NOTIFICATION_INDEX",
    )

    response = client.get("/api/v1/source-endpoints")

    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == {
        "Recruitment notices",
        "Notification archive",
    }


def test_unknown_authority_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/source-endpoints",
        json=endpoint_payload(str(uuid.uuid4())),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Recruiting authority not found"


def test_duplicate_canonical_url_returns_conflict(client: TestClient) -> None:
    authority = create_authority(client)
    create_endpoint(
        client,
        authority["id"],
        canonical_url="https://jobs.example.gov.in/",
    )

    response = client.post(
        "/api/v1/source-endpoints",
        json=endpoint_payload(
            authority["id"],
            name="Formatting duplicate",
            canonical_url="HTTPS://JOBS.EXAMPLE.GOV.IN:443#notices",
        ),
    )

    assert response.status_code == 409
    assert "already registered" in response.json()["detail"]


def test_invalid_url_is_rejected(client: TestClient) -> None:
    authority = create_authority(client)

    response = client.post(
        "/api/v1/source-endpoints",
        json=endpoint_payload(authority["id"], canonical_url="ftp://example.gov.in/notices"),
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("query", "expected_name"),
    [
        ("status=INACTIVE", "Secondary notices"),
        ("discovery_enabled=false", "Secondary notices"),
        ("source_type=DOCUMENT_LISTING", "Secondary notices"),
        ("source_class=OFFICIAL_SUPPORTING", "Secondary notices"),
    ],
)
def test_filter_endpoints(client: TestClient, query: str, expected_name: str) -> None:
    authority = create_authority(client)
    create_endpoint(client, authority["id"])
    create_endpoint(
        client,
        authority["id"],
        name="Secondary notices",
        canonical_url="https://support.example.gov.in/documents",
        source_type="DOCUMENT_LISTING",
        source_class="OFFICIAL_SUPPORTING",
        status="INACTIVE",
        discovery_enabled=False,
    )

    response = client.get(f"/api/v1/source-endpoints?{query}")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == [expected_name]


def test_filter_endpoints_by_authority(client: TestClient) -> None:
    first = create_authority(client)
    second = create_authority(
        client,
        code="SECOND_BOARD",
        name="Second Board",
        authority_type="BOARD",
        official_website_url="https://board.example.gov.in",
    )
    create_endpoint(client, first["id"])
    create_endpoint(
        client,
        second["id"],
        name="Second board notices",
        canonical_url="https://board.example.gov.in/notices",
    )

    response = client.get(
        "/api/v1/source-endpoints",
        params={"recruiting_authority_id": second["id"]},
    )

    assert response.status_code == 200
    assert [item["recruiting_authority_id"] for item in response.json()] == [second["id"]]


def test_update_endpoint_operational_metadata(client: TestClient) -> None:
    authority = create_authority(client)
    endpoint = create_endpoint(client, authority["id"], adapter_key="generic-listing")

    response = client.patch(
        f"/api/v1/source-endpoints/{endpoint['id']}",
        json={
            "status": "DISABLED",
            "discovery_enabled": False,
            "adapter_key": None,
            "provenance_note": "Disabled after registry review.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DISABLED"
    assert body["discovery_enabled"] is False
    assert body["adapter_key"] is None
    assert body["provenance_note"] == "Disabled after registry review."


def test_unknown_endpoint_returns_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/source-endpoints/{uuid.uuid4()}")

    assert response.status_code == 404
