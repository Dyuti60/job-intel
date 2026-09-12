import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.evidence import CandidateFieldEvidence, Evidence, EvidenceType
from tests.factories import (
    create_candidate_evidence_graph,
    create_evidence,
    create_run,
    observe_document,
)


def test_evidence_identity_unique_constraint(
    client: TestClient, db_session: Session
) -> None:
    document, _, _ = create_candidate_evidence_graph(client)
    values = {
        "source_document_id": uuid.UUID(document["id"]),
        "evidence_type": EvidenceType.TEXT_EXCERPT,
        "excerpt": "Database uniqueness",
        "evidence_hash": "a" * 64,
    }
    db_session.add_all(
        [Evidence(id=uuid.uuid4(), **values), Evidence(id=uuid.uuid4(), **values)]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_candidate_field_evidence_link_unique_constraint(
    client: TestClient, db_session: Session
) -> None:
    document, _, revision = create_candidate_evidence_graph(client)
    evidence = create_evidence(client, document["id"])
    values = {
        "candidate_field_id": uuid.UUID(revision["fields"][0]["id"]),
        "evidence_id": uuid.UUID(evidence["id"]),
        "source_document_id": uuid.UUID(document["id"]),
    }
    db_session.add_all(
        [
            CandidateFieldEvidence(id=uuid.uuid4(), **values),
            CandidateFieldEvidence(id=uuid.uuid4(), **values),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_database_rejects_cross_document_link(
    client: TestClient, db_session: Session
) -> None:
    document, _, revision = create_candidate_evidence_graph(client)
    endpoint_id = client.get(f"/api/v1/source-documents/{document['id']}").json()[
        "source_endpoint_id"
    ]
    second_run = create_run(client, endpoint_id)
    other_document = observe_document(
        client, second_run["id"], content_text="other source version"
    )["document"]
    other_evidence = create_evidence(client, other_document["id"])
    db_session.add(
        CandidateFieldEvidence(
            candidate_field_id=uuid.UUID(revision["fields"][0]["id"]),
            evidence_id=uuid.UUID(other_evidence["id"]),
            source_document_id=uuid.UUID(document["id"]),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
