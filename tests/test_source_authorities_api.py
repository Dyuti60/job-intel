import uuid

from fastapi.testclient import TestClient

from tests.factories import authority_payload, create_authority


def test_create_authority_normalizes_code_and_url(client: TestClient) -> None:
    response = client.post(
        "/api/v1/source-authorities",
        json=authority_payload(
            code=" apsc ",
            official_website_url="HTTPS://APSC.EXAMPLE.GOV.IN:443#about",
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "APSC"
    assert body["official_website_url"] == "https://apsc.example.gov.in/"
    assert body["status"] == "ACTIVE"
    assert body["created_at"]


def test_retrieve_authority(client: TestClient) -> None:
    authority = create_authority(client)

    response = client.get(f"/api/v1/source-authorities/{authority['id']}")

    assert response.status_code == 200
    assert response.json() == authority


def test_list_authorities(client: TestClient) -> None:
    create_authority(client)
    create_authority(
        client,
        code="SLPRB_ASSAM",
        name="State Level Police Recruitment Board",
        authority_type="POLICE",
        official_website_url="https://police.example.gov.in",
        status="INACTIVE",
    )

    response = client.get("/api/v1/source-authorities")

    assert response.status_code == 200
    assert [item["code"] for item in response.json()] == ["APSC", "SLPRB_ASSAM"]


def test_duplicate_authority_code_returns_conflict(client: TestClient) -> None:
    create_authority(client)

    response = client.post(
        "/api/v1/source-authorities",
        json=authority_payload(name="Duplicate authority"),
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_invalid_authority_type_and_status_are_rejected(client: TestClient) -> None:
    invalid_type = client.post(
        "/api/v1/source-authorities",
        json=authority_payload(authority_type="MINISTRY"),
    )
    invalid_status = client.post(
        "/api/v1/source-authorities",
        json=authority_payload(status="DELETED"),
    )

    assert invalid_type.status_code == 422
    assert invalid_status.status_code == 422


def test_unknown_authority_returns_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/source-authorities/{uuid.uuid4()}")

    assert response.status_code == 404


def test_update_authority_status(client: TestClient) -> None:
    authority = create_authority(client)

    response = client.patch(
        f"/api/v1/source-authorities/{authority['id']}",
        json={"status": "INACTIVE"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "INACTIVE"
