from fastapi.testclient import TestClient


def authority_payload(**overrides) -> dict:
    payload = {
        "code": "APSC",
        "name": "Assam Public Service Commission",
        "authority_type": "COMMISSION",
        "official_website_url": "https://apsc.example.gov.in",
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_authority(client: TestClient, **overrides) -> dict:
    response = client.post("/api/v1/source-authorities", json=authority_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def endpoint_payload(authority_id: str, **overrides) -> dict:
    payload = {
        "recruiting_authority_id": authority_id,
        "name": "Recruitment notices",
        "canonical_url": "https://jobs.example.gov.in/recruitment",
        "source_type": "RECRUITMENT_INDEX",
        "source_class": "AUTHORITATIVE_OFFICIAL",
        "status": "ACTIVE",
        "discovery_enabled": True,
        "adapter_key": None,
        "last_verified_at": "2026-09-12T10:00:00+05:30",
        "provenance_note": "Verified against the authority website.",
    }
    payload.update(overrides)
    return payload


def create_endpoint(client: TestClient, authority_id: str, **overrides) -> dict:
    response = client.post(
        "/api/v1/source-endpoints",
        json=endpoint_payload(authority_id, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_discovery_source(
    client: TestClient,
    *,
    authority_overrides: dict | None = None,
    endpoint_overrides: dict | None = None,
) -> tuple[dict, dict]:
    authority = create_authority(client, **(authority_overrides or {}))
    endpoint = create_endpoint(client, authority["id"], **(endpoint_overrides or {}))
    return authority, endpoint


def create_run(client: TestClient, endpoint_id: str, trigger_type: str = "MANUAL") -> dict:
    response = client.post(
        "/api/v1/discovery-runs",
        json={"source_endpoint_id": endpoint_id, "trigger_type": trigger_type},
    )
    assert response.status_code == 201, response.text
    return response.json()


def document_payload(**overrides) -> dict:
    payload = {
        "document_url": "https://jobs.example.gov.in/notices/notice-1.pdf",
        "document_type": "PDF",
        "content_type": "application/pdf",
        "content_text": "controlled test document",
        "http_status_code": 200,
        "http_etag": "\"fixture-v1\"",
        "http_last_modified": "Fri, 12 Sep 2026 04:30:00 GMT",
        "storage_uri": "file:///fixtures/notice-1.pdf",
    }
    payload.update(overrides)
    return payload


def observe_document(client: TestClient, run_id: str, **overrides) -> dict:
    response = client.post(
        f"/api/v1/discovery-runs/{run_id}/documents",
        json=document_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()
