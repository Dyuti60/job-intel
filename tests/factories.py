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
