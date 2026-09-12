import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.discovery import SourceDocument, SourceDocumentStatus
from app.services.evidence_values import (
    EVIDENCE_CONTEXT_MAX_LENGTH,
    EVIDENCE_EXCERPT_MAX_LENGTH,
)
from tests.factories import (
    create_candidate_evidence_graph,
    create_evidence,
    evidence_payload,
)


def test_create_retrieve_and_filter_evidence(client: TestClient) -> None:
    document, _, _ = create_candidate_evidence_graph(client)
    first = create_evidence(client, document["id"])
    second = create_evidence(
        client,
        document["id"],
        evidence_type="DOCUMENT_METADATA",
        excerpt="Notification dated 12 September 2026.",
    )

    retrieved = client.get(f"/api/v1/evidence/{first['id']}")
    by_document = client.get(
        "/api/v1/evidence", params={"source_document_id": document["id"]}
    )
    by_type = client.get(
        "/api/v1/evidence", params={"evidence_type": "DOCUMENT_METADATA"}
    )

    assert retrieved.status_code == 200
    assert retrieved.json() == first
    assert {item["id"] for item in by_document.json()} == {first["id"], second["id"]}
    assert [item["id"] for item in by_type.json()] == [second["id"]]
    assert len(first["evidence_hash"]) == 64


def test_unknown_source_document_and_evidence_are_rejected(client: TestClient) -> None:
    unknown_id = str(uuid.uuid4())

    created = client.post("/api/v1/evidence", json=evidence_payload(unknown_id))
    retrieved = client.get(f"/api/v1/evidence/{unknown_id}")

    assert created.status_code == 404
    assert retrieved.status_code == 404


@pytest.mark.parametrize(
    "document_status",
    [SourceDocumentStatus.FAILED, SourceDocumentStatus.UNAVAILABLE],
)
def test_unusable_source_document_is_rejected(
    client: TestClient,
    db_session: Session,
    document_status: SourceDocumentStatus,
) -> None:
    document, _, _ = create_candidate_evidence_graph(client)
    persisted = db_session.get(SourceDocument, uuid.UUID(document["id"]))
    assert persisted is not None
    persisted.status = document_status
    db_session.commit()

    response = client.post("/api/v1/evidence", json=evidence_payload(document["id"]))

    assert response.status_code == 409
    assert document_status.value in response.json()["detail"]


def test_invalid_evidence_type_is_rejected(client: TestClient) -> None:
    document, _, _ = create_candidate_evidence_graph(client)

    response = client.post(
        "/api/v1/evidence",
        json=evidence_payload(document["id"], evidence_type="CONFIRMING"),
    )

    assert response.status_code == 422


def test_evidence_text_and_locator_are_normalized(client: TestClient) -> None:
    document, _, _ = create_candidate_evidence_graph(client)

    evidence = create_evidence(
        client,
        document["id"],
        source_locator="  page=4; section=Eligibility  ",
        excerpt="  Cafe\u0301\r\nMaximum age: 38 years.  ",
        context="  Age limits\rapply on the reference date.  ",
    )

    assert evidence["source_locator"] == "page=4; section=Eligibility"
    assert evidence["excerpt"] == "Café\nMaximum age: 38 years."
    assert evidence["context"] == "Age limits\napply on the reference date."


def test_blank_excerpt_is_rejected(client: TestClient) -> None:
    document, _, _ = create_candidate_evidence_graph(client)

    response = client.post(
        "/api/v1/evidence",
        json=evidence_payload(document["id"], excerpt=" \r\n "),
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("excerpt", "x" * (EVIDENCE_EXCERPT_MAX_LENGTH + 1)),
        ("context", "x" * (EVIDENCE_CONTEXT_MAX_LENGTH + 1)),
    ],
)
def test_evidence_text_limits_are_enforced(
    client: TestClient, field: str, value: str
) -> None:
    document, _, _ = create_candidate_evidence_graph(client)

    response = client.post(
        "/api/v1/evidence",
        json=evidence_payload(document["id"], **{field: value}),
    )

    assert response.status_code == 422


def test_identical_evidence_submission_is_idempotent(client: TestClient) -> None:
    document, _, _ = create_candidate_evidence_graph(client)
    first = create_evidence(client, document["id"])

    replay = client.post("/api/v1/evidence", json=evidence_payload(document["id"]))
    listed = client.get(
        "/api/v1/evidence", params={"source_document_id": document["id"]}
    )

    assert replay.status_code == 200
    assert replay.json()["id"] == first["id"]
    assert len(listed.json()) == 1
