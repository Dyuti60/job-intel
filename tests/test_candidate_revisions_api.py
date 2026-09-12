import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.discovery import SourceDocument, SourceDocumentStatus
from tests.factories import (
    candidate_fields,
    create_authority,
    create_candidate,
    create_discovery_source,
    create_revision,
    create_run,
    observe_document,
    revision_payload,
)


def create_candidate_and_document(client: TestClient) -> tuple[dict, dict]:
    authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    candidate = create_candidate(client, authority["id"])
    return candidate, document


def test_create_first_revision_with_exact_provenance(client: TestClient) -> None:
    candidate, document = create_candidate_and_document(client)

    revision = create_revision(client, candidate["id"], document["id"])

    assert revision["revision_number"] == 1
    assert revision["source_document_id"] == document["id"]
    assert len(revision["revision_hash"]) == 64
    assert {field["source_document_id"] for field in revision["fields"]} == {
        document["id"]
    }
    assert {field["field_path"] for field in revision["fields"]} == {
        "recruitment_name",
        "vacancies.total",
    }


def test_candidate_source_authority_mismatch_is_rejected(client: TestClient) -> None:
    first_authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    second_authority = create_authority(
        client,
        code="OTHER_AUTHORITY",
        name="Other Authority",
        official_website_url="https://other.example.gov.in",
    )
    candidate = create_candidate(
        client,
        second_authority["id"],
        candidate_key="OTHER_RECRUITMENT",
    )

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(document["id"]),
    )

    assert first_authority["id"] != second_authority["id"]
    assert response.status_code == 409
    assert "does not match" in response.json()["detail"]


@pytest.mark.parametrize(
    "document_status",
    [SourceDocumentStatus.FAILED, SourceDocumentStatus.UNAVAILABLE],
)
def test_nonactive_source_document_is_rejected(
    client: TestClient,
    db_session: Session,
    document_status: SourceDocumentStatus,
) -> None:
    candidate, document = create_candidate_and_document(client)
    persisted = db_session.get(SourceDocument, uuid.UUID(document["id"]))
    assert persisted is not None
    persisted.status = document_status
    db_session.commit()

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(document["id"]),
    )

    assert response.status_code == 409
    assert document_status.value in response.json()["detail"]


def test_duplicate_field_path_is_rejected(client: TestClient) -> None:
    candidate, document = create_candidate_and_document(client)
    duplicate_fields = candidate_fields()
    duplicate_fields.append(
        {
            "field_path": "vacancies.total",
            "value_type": "INTEGER",
            "value": 43,
        }
    )

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(document["id"], fields=duplicate_fields),
    )

    assert response.status_code == 422
    assert "field_path values must be unique" in response.text


def test_empty_field_collection_is_rejected(client: TestClient) -> None:
    candidate, document = create_candidate_and_document(client)

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(document["id"], fields=[]),
    )

    assert response.status_code == 422


def test_invalid_field_path_is_rejected(client: TestClient) -> None:
    candidate, document = create_candidate_and_document(client)

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(
            document["id"],
            fields=[
                {
                    "field_path": "Invalid Field Path",
                    "value_type": "STRING",
                    "value": "invalid",
                }
            ],
        ),
    )

    assert response.status_code == 422


def test_exact_revision_replay_is_idempotent(client: TestClient) -> None:
    candidate, document = create_candidate_and_document(client)
    first = create_revision(client, candidate["id"], document["id"])

    replay = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(
            document["id"],
            extraction_note="A volatile note that is not part of identity.",
        ),
    )

    assert replay.status_code == 200
    assert replay.json()["id"] == first["id"]
    assert replay.json()["revision_number"] == 1
    assert len(replay.json()["fields"]) == len(first["fields"])


def test_field_order_does_not_create_duplicate_revision(client: TestClient) -> None:
    candidate, document = create_candidate_and_document(client)
    first = create_revision(client, candidate["id"], document["id"])

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(document["id"], fields=list(reversed(candidate_fields()))),
    )

    assert response.status_code == 200
    assert response.json()["revision_hash"] == first["revision_hash"]
    assert response.json()["id"] == first["id"]


def test_changed_field_creates_revision_two_and_preserves_revision_one(
    client: TestClient,
) -> None:
    candidate, document = create_candidate_and_document(client)
    first = create_revision(client, candidate["id"], document["id"])
    changed_fields = candidate_fields()
    changed_fields[1]["value"] = 43

    second = create_revision(
        client,
        candidate["id"],
        document["id"],
        fields=changed_fields,
    )

    assert second["revision_number"] == 2
    assert second["revision_hash"] != first["revision_hash"]
    old = client.get(f"/api/v1/candidate-revisions/{first['id']}").json()
    assert next(
        field["value"] for field in old["fields"] if field["field_path"] == "vacancies.total"
    ) == 42
    assert next(
        field["value"] for field in second["fields"] if field["field_path"] == "vacancies.total"
    ) == 43


def test_changed_source_document_creates_new_revision(client: TestClient) -> None:
    authority, endpoint = create_discovery_source(client)
    first_run = create_run(client, endpoint["id"])
    first_document = observe_document(client, first_run["id"], content_text="version 1")[
        "document"
    ]
    second_run = create_run(client, endpoint["id"])
    second_document = observe_document(client, second_run["id"], content_text="version 2")[
        "document"
    ]
    candidate = create_candidate(client, authority["id"])
    first = create_revision(client, candidate["id"], first_document["id"])

    second = create_revision(client, candidate["id"], second_document["id"])

    assert first["source_document_id"] != second["source_document_id"]
    assert first["revision_hash"] != second["revision_hash"]
    assert second["revision_number"] == 2


def test_revision_list_get_and_fields_routes(client: TestClient) -> None:
    candidate, document = create_candidate_and_document(client)
    revision = create_revision(client, candidate["id"], document["id"])

    listed = client.get(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions"
    )
    retrieved = client.get(f"/api/v1/candidate-revisions/{revision['id']}")
    fields = client.get(f"/api/v1/candidate-revisions/{revision['id']}/fields")

    assert [item["id"] for item in listed.json()] == [revision["id"]]
    assert retrieved.json() == revision
    assert fields.json() == revision["fields"]


def test_historical_revision_has_no_mutation_api(client: TestClient) -> None:
    candidate, document = create_candidate_and_document(client)
    revision = create_revision(client, candidate["id"], document["id"])

    response = client.patch(
        f"/api/v1/candidate-revisions/{revision['id']}",
        json={"revision_number": 99},
    )

    assert response.status_code == 405


def test_discarded_candidate_rejects_new_revision(client: TestClient) -> None:
    candidate, document = create_candidate_and_document(client)
    discarded = client.patch(
        f"/api/v1/recruitment-candidates/{candidate['id']}",
        json={"status": "DISCARDED"},
    )
    assert discarded.status_code == 200

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(document["id"]),
    )

    assert response.status_code == 409
    assert "Discarded candidates" in response.json()["detail"]


def test_unknown_candidate_and_document_are_rejected(client: TestClient) -> None:
    authority = create_authority(client)
    candidate = create_candidate(client, authority["id"])

    unknown_candidate = client.post(
        f"/api/v1/recruitment-candidates/{uuid.uuid4()}/revisions",
        json=revision_payload(str(uuid.uuid4())),
    )
    unknown_document = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(str(uuid.uuid4())),
    )

    assert unknown_candidate.status_code == 404
    assert unknown_document.status_code == 404
