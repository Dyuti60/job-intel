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


def candidate_payload(authority_id: str, **overrides) -> dict:
    payload = {
        "recruiting_authority_id": authority_id,
        "candidate_key": "APSC_ADVT_12_2026",
        "display_name": "Combined Competitive Recruitment 2026",
    }
    payload.update(overrides)
    return payload


def create_candidate(client: TestClient, authority_id: str, **overrides) -> dict:
    response = client.post(
        "/api/v1/recruitment-candidates",
        json=candidate_payload(authority_id, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def candidate_fields() -> list[dict]:
    return [
        {
            "field_path": "recruitment_name",
            "value_type": "STRING",
            "value": "Combined Competitive Recruitment",
            "raw_value": "Combined Competitive Examination",
            "source_locator": "page=1",
        },
        {
            "field_path": "vacancies.total",
            "value_type": "INTEGER",
            "value": 42,
            "raw_value": "Total posts: 42",
            "source_locator": "page=2",
        },
    ]


def revision_payload(document_id: str, **overrides) -> dict:
    payload = {
        "source_document_id": document_id,
        "fields": candidate_fields(),
        "extraction_method": "CONTROLLED_INPUT",
        "extraction_note": "T-004 test fixture.",
    }
    payload.update(overrides)
    return payload


def create_revision(
    client: TestClient,
    candidate_id: str,
    document_id: str,
    **overrides,
) -> dict:
    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate_id}/revisions",
        json=revision_payload(document_id, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_candidate_evidence_graph(client: TestClient) -> tuple[dict, dict, dict]:
    authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    candidate = create_candidate(client, authority["id"])
    revision = create_revision(client, candidate["id"], document["id"])
    return document, candidate, revision


def evidence_payload(document_id: str, **overrides) -> dict:
    payload = {
        "source_document_id": document_id,
        "evidence_type": "TEXT_EXCERPT",
        "source_locator": "page=4;section=Eligibility",
        "excerpt": "Candidates must be between 21 and 38 years of age.",
        "context": "Age limits as on 01-01-2026.",
    }
    payload.update(overrides)
    return payload


def create_evidence(client: TestClient, document_id: str, **overrides) -> dict:
    response = client.post(
        "/api/v1/evidence",
        json=evidence_payload(document_id, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_ready_candidate_revision(
    client: TestClient,
    *,
    fields: list[dict] | None = None,
    authority_overrides: dict | None = None,
    endpoint_overrides: dict | None = None,
) -> tuple[dict, dict, dict, dict]:
    authority, endpoint = create_discovery_source(
        client,
        authority_overrides=authority_overrides,
        endpoint_overrides=endpoint_overrides,
    )
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    candidate_overrides = {}
    if authority_overrides and authority_overrides.get("code"):
        candidate_overrides["candidate_key"] = (
            f"{authority_overrides['code']}_RECRUITMENT"
        )
    candidate = create_candidate(client, authority["id"], **candidate_overrides)
    revision = create_revision(
        client,
        candidate["id"],
        document["id"],
        **({"fields": fields} if fields is not None else {}),
    )
    ready = client.patch(
        f"/api/v1/recruitment-candidates/{candidate['id']}",
        json={"status": "READY_FOR_VERIFICATION"},
    )
    assert ready.status_code == 200, ready.text
    return authority, document, ready.json(), revision


def create_verification_run(
    client: TestClient,
    revision_id: str,
    trigger_type: str = "MANUAL",
) -> dict:
    response = client.post(
        "/api/v1/verification-runs",
        json={
            "candidate_revision_id": revision_id,
            "trigger_type": trigger_type,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def start_verification_run(client: TestClient, run_id: str) -> dict:
    response = client.post(f"/api/v1/verification-runs/{run_id}/start")
    assert response.status_code == 200, response.text
    return response.json()


def create_field_verification(
    client: TestClient, run_id: str, field_id: str
) -> dict:
    response = client.post(
        f"/api/v1/verification-runs/{run_id}/fields/{field_id}"
    )
    assert response.status_code == 201, response.text
    return response.json()


def add_verification_assessment(
    client: TestClient,
    verification_id: str,
    evidence_id: str,
    assessment: str,
    **overrides,
) -> dict:
    payload = {
        "evidence_id": evidence_id,
        "assessment": assessment,
    }
    payload.update(overrides)
    response = client.post(
        f"/api/v1/field-verifications/{verification_id}/evidence",
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def finalize_field_verification(
    client: TestClient, verification_id: str, *, not_applicable: bool = False
) -> dict:
    response = client.post(
        f"/api/v1/field-verifications/{verification_id}/finalize",
        json={"not_applicable": not_applicable},
    )
    assert response.status_code == 200, response.text
    return response.json()
