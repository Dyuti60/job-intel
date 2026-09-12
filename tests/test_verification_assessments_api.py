import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.discovery import SourceDocument, SourceDocumentStatus
from app.models.evidence import Evidence
from tests.factories import (
    add_verification_assessment,
    create_authority,
    create_endpoint,
    create_evidence,
    create_field_verification,
    create_ready_candidate_revision,
    create_run,
    create_verification_run,
    observe_document,
    start_verification_run,
)


def maximum_age_field() -> list[dict]:
    return [
        {
            "field_path": "eligibility.maximum_age",
            "value_type": "INTEGER",
            "value": 38,
            "raw_value": "Maximum age is 38 years",
            "source_locator": "page=4",
        }
    ]


def running_field_verification(client: TestClient) -> tuple[dict, dict, dict]:
    _, document, _, revision = create_ready_candidate_revision(
        client, fields=maximum_age_field()
    )
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    verification = create_field_verification(
        client, run["id"], revision["fields"][0]["id"]
    )
    return document, run, verification


def create_other_source_document(
    client: TestClient, *, suffix: str, source_class: str
) -> dict:
    authority = create_authority(
        client,
        code=f"VERIFY_{suffix}",
        name=f"Verification {suffix}",
        official_website_url=f"https://{suffix.lower()}.example.gov.in",
    )
    endpoint = create_endpoint(
        client,
        authority["id"],
        name=f"{suffix} notices",
        canonical_url=f"https://{suffix.lower()}.example.gov.in/notices",
        source_class=source_class,
    )
    run = create_run(client, endpoint["id"])
    return observe_document(
        client,
        run["id"],
        document_url=f"https://{suffix.lower()}.example.gov.in/notice.pdf",
        content_text=f"{suffix} verification content",
    )["document"]


def test_assessments_allow_same_document_cross_document_and_cross_source(
    client: TestClient,
) -> None:
    document, _, verification = running_field_verification(client)
    same_evidence = create_evidence(client, document["id"])
    endpoint_id = client.get(f"/api/v1/source-documents/{document['id']}").json()[
        "source_endpoint_id"
    ]
    another_run = create_run(client, endpoint_id)
    changed_document = observe_document(
        client,
        another_run["id"],
        content_text="changed official version",
    )["document"]
    changed_evidence = create_evidence(
        client, changed_document["id"], excerpt="Official context only."
    )
    secondary_document = create_other_source_document(
        client,
        suffix="SECONDARY",
        source_class="SECONDARY_DISCOVERY_ONLY",
    )
    secondary_evidence = create_evidence(
        client, secondary_document["id"], excerpt="Secondary source says age 35."
    )

    first = add_verification_assessment(
        client,
        verification["id"],
        same_evidence["id"],
        "SUPPORTS",
        asserted_value=38,
        asserted_value_type="INTEGER",
    )
    second = add_verification_assessment(
        client,
        verification["id"],
        changed_evidence["id"],
        "CONTEXT_ONLY",
    )
    third = add_verification_assessment(
        client,
        verification["id"],
        secondary_evidence["id"],
        "CONTRADICTS",
        asserted_value=35,
        asserted_value_type="INTEGER",
    )

    assert len(first["assessments"]) == 1
    assert len(second["assessments"]) == 2
    assert len(third["assessments"]) == 3
    by_id = {item["evidence_id"]: item for item in third["assessments"]}
    assert by_id[same_evidence["id"]]["source_class"] == "AUTHORITATIVE_OFFICIAL"
    assert by_id[secondary_evidence["id"]]["source_class"] == (
        "SECONDARY_DISCOVERY_ONLY"
    )
    assert by_id[changed_evidence["id"]]["source_document_id"] == (
        changed_document["id"]
    )


def test_client_cannot_supply_source_class(client: TestClient) -> None:
    document, _, verification = running_field_verification(client)
    evidence = create_evidence(client, document["id"])

    response = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={
            "evidence_id": evidence["id"],
            "assessment": "SUPPORTS",
            "asserted_value": 38,
            "asserted_value_type": "INTEGER",
            "source_class": "SECONDARY_DISCOVERY_ONLY",
        },
    )

    assert response.status_code == 422


def test_unknown_evidence_is_rejected(client: TestClient) -> None:
    _, _, verification = running_field_verification(client)

    response = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={"evidence_id": str(uuid.uuid4()), "assessment": "CONTEXT_ONLY"},
    )

    assert response.status_code == 404


def test_duplicate_assessment_replay_is_idempotent(client: TestClient) -> None:
    document, _, verification = running_field_verification(client)
    evidence = create_evidence(client, document["id"])
    payload = {
        "evidence_id": evidence["id"],
        "assessment": "SUPPORTS",
        "asserted_value": 38,
        "asserted_value_type": "INTEGER",
        "assessment_note": "Exact official value.",
    }
    first = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence", json=payload
    )
    replay = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence", json=payload
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["assessments"] == first.json()["assessments"]

    changed = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={**payload, "assessment_note": "Changed note"},
    )
    assert changed.status_code == 409


def test_asserted_value_consistency_rules(client: TestClient) -> None:
    document, _, verification = running_field_verification(client)
    evidence = [
        create_evidence(client, document["id"], excerpt=f"Evidence {index}")
        for index in range(4)
    ]

    supports_equal = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={
            "evidence_id": evidence[0]["id"],
            "assessment": "SUPPORTS",
            "asserted_value": 38,
            "asserted_value_type": "INTEGER",
        },
    )
    supports_different = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={
            "evidence_id": evidence[1]["id"],
            "assessment": "SUPPORTS",
            "asserted_value": 35,
            "asserted_value_type": "INTEGER",
        },
    )
    contradicts_different = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={
            "evidence_id": evidence[2]["id"],
            "assessment": "CONTRADICTS",
            "asserted_value": 35,
            "asserted_value_type": "INTEGER",
        },
    )
    contradicts_equal = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={
            "evidence_id": evidence[3]["id"],
            "assessment": "CONTRADICTS",
            "asserted_value": 38,
            "asserted_value_type": "INTEGER",
        },
    )

    assert supports_equal.status_code == 201
    assert supports_different.status_code == 409
    assert contradicts_different.status_code == 201
    assert contradicts_equal.status_code == 409


def test_context_only_without_asserted_value_and_decimal_normalization(
    client: TestClient,
) -> None:
    document, _, verification = running_field_verification(client)
    context = create_evidence(client, document["id"], excerpt="Reference date context")
    context_response = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={"evidence_id": context["id"], "assessment": "CONTEXT_ONLY"},
    )
    assert context_response.status_code == 201
    assert context_response.json()["assessments"][0]["asserted_value_type"] is None

    decimal_fields = [
        {
            "field_path": "application.fee",
            "value_type": "DECIMAL",
            "value": "100.500",
        }
    ]
    _, decimal_document, _, revision = create_ready_candidate_revision(
        client,
        fields=decimal_fields,
        authority_overrides={
            "code": "DECIMAL_AUTHORITY",
            "name": "Decimal Authority",
            "official_website_url": "https://decimal.example.gov.in",
        },
        endpoint_overrides={
            "canonical_url": "https://decimal.example.gov.in/notices"
        },
    )
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    decimal_verification = create_field_verification(
        client, run["id"], revision["fields"][0]["id"]
    )
    evidence = create_evidence(client, decimal_document["id"], excerpt="Fee is 100.50")
    response = add_verification_assessment(
        client,
        decimal_verification["id"],
        evidence["id"],
        "SUPPORTS",
        asserted_value="100.5000",
        asserted_value_type="DECIMAL",
    )

    assert response["assessments"][0]["asserted_value"] == "100.5"


@pytest.mark.parametrize(
    "document_status",
    [SourceDocumentStatus.FAILED, SourceDocumentStatus.UNAVAILABLE],
)
def test_unusable_evidence_source_document_is_rejected(
    client: TestClient,
    db_session: Session,
    document_status: SourceDocumentStatus,
) -> None:
    document, _, verification = running_field_verification(client)
    unusable = create_evidence(client, document["id"], excerpt="Unavailable evidence")
    persisted_document = db_session.get(SourceDocument, uuid.UUID(document["id"]))
    assert persisted_document is not None
    persisted_document.status = document_status
    db_session.commit()

    unavailable_response = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={"evidence_id": unusable["id"], "assessment": "CONTEXT_ONLY"},
    )
    assert unavailable_response.status_code == 409


def test_tampered_evidence_integrity_is_rejected(
    client: TestClient, db_session: Session
) -> None:
    document, _, verification = running_field_verification(client)
    evidence = create_evidence(client, document["id"], excerpt="Integrity evidence")

    persisted_evidence = db_session.get(Evidence, uuid.UUID(evidence["id"]))
    assert persisted_evidence is not None
    persisted_evidence.evidence_hash = "f" * 64
    db_session.commit()
    tampered_response = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={"evidence_id": evidence["id"], "assessment": "CONTEXT_ONLY"},
    )
    assert tampered_response.status_code == 409
    assert "integrity" in tampered_response.json()["detail"]
