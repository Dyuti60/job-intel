import uuid

from fastapi.testclient import TestClient

from tests.factories import (
    create_candidate,
    create_discovery_source,
    create_evidence,
    create_revision,
    create_run,
    observe_document,
)


def age_revision_fields() -> list[dict]:
    return [
        {
            "field_path": "eligibility.minimum_age",
            "value_type": "INTEGER",
            "value": 21,
            "raw_value": "between 21 and 38 years",
            "source_locator": "page=4",
        },
        {
            "field_path": "eligibility.maximum_age",
            "value_type": "INTEGER",
            "value": 38,
            "raw_value": "between 21 and 38 years",
            "source_locator": "page=4",
        },
    ]


def create_age_graph(client: TestClient) -> tuple[dict, dict, dict]:
    authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    candidate = create_candidate(client, authority["id"])
    revision = create_revision(
        client,
        candidate["id"],
        document["id"],
        fields=age_revision_fields(),
    )
    assert revision["revision_number"] == 1
    return document, candidate, revision


def test_one_evidence_supports_multiple_fields_and_second_evidence_can_link(
    client: TestClient,
) -> None:
    document, candidate, revision = create_age_graph(client)
    minimum, maximum = revision["fields"]
    passage = create_evidence(client, document["id"])
    reference_date = create_evidence(
        client,
        document["id"],
        source_locator="page=4;section=Age limits",
        excerpt="Age shall be calculated as on 01-01-2026.",
    )

    minimum_passage = client.post(
        f"/api/v1/candidate-fields/{minimum['id']}/evidence/{passage['id']}"
    )
    maximum_passage = client.post(
        f"/api/v1/candidate-fields/{maximum['id']}/evidence/{passage['id']}"
    )
    minimum_reference = client.post(
        f"/api/v1/candidate-fields/{minimum['id']}/evidence/{reference_date['id']}"
    )

    assert minimum_passage.status_code == 201
    assert maximum_passage.status_code == 201
    assert minimum_reference.status_code == 201
    minimum_evidence = client.get(
        f"/api/v1/candidate-fields/{minimum['id']}/evidence"
    ).json()
    assert {item["id"] for item in minimum_evidence} == {
        passage["id"],
        reference_date["id"],
    }
    assert [
        item["id"]
        for item in client.get(
            f"/api/v1/candidate-fields/{maximum['id']}/evidence"
        ).json()
    ] == [passage["id"]]

    current_revision = client.get(
        f"/api/v1/candidate-revisions/{revision['id']}"
    ).json()
    current_candidate = client.get(
        f"/api/v1/recruitment-candidates/{candidate['id']}"
    ).json()
    assert current_revision == revision
    assert current_candidate["status"] == "DRAFT"
    assert {field["value"] for field in current_revision["fields"]} == {21, 38}


def test_repeated_link_is_idempotent(client: TestClient) -> None:
    document, _, revision = create_age_graph(client)
    field = revision["fields"][0]
    evidence = create_evidence(client, document["id"])
    first = client.post(
        f"/api/v1/candidate-fields/{field['id']}/evidence/{evidence['id']}"
    )

    replay = client.post(
        f"/api/v1/candidate-fields/{field['id']}/evidence/{evidence['id']}"
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert len(
        client.get(f"/api/v1/candidate-fields/{field['id']}/evidence").json()
    ) == 1


def test_cross_document_evidence_link_is_rejected(client: TestClient) -> None:
    document, _, revision = create_age_graph(client)
    run_response = client.get(f"/api/v1/source-documents/{document['id']}")
    assert run_response.status_code == 200

    # A changed version at the same endpoint has a different immutable document identity.
    endpoint_id = run_response.json()["source_endpoint_id"]
    second_run = create_run(client, endpoint_id)
    other_document = observe_document(
        client, second_run["id"], content_text="changed document version"
    )["document"]
    other_evidence = create_evidence(client, other_document["id"])

    response = client.post(
        f"/api/v1/candidate-fields/{revision['fields'][0]['id']}"
        f"/evidence/{other_evidence['id']}"
    )

    assert response.status_code == 409
    assert "same source document" in response.json()["detail"]


def test_unknown_candidate_field_and_evidence_are_rejected(client: TestClient) -> None:
    document, _, revision = create_age_graph(client)
    evidence = create_evidence(client, document["id"])
    unknown_field = str(uuid.uuid4())
    unknown_evidence = str(uuid.uuid4())

    field_response = client.post(
        f"/api/v1/candidate-fields/{unknown_field}/evidence/{evidence['id']}"
    )
    evidence_response = client.post(
        f"/api/v1/candidate-fields/{revision['fields'][0]['id']}"
        f"/evidence/{unknown_evidence}"
    )
    list_response = client.get(
        f"/api/v1/candidate-fields/{unknown_field}/evidence"
    )

    assert field_response.status_code == 404
    assert evidence_response.status_code == 404
    assert list_response.status_code == 404


def test_changed_source_version_evidence_is_distinct(client: TestClient) -> None:
    authority, endpoint = create_discovery_source(client)
    first_run = create_run(client, endpoint["id"])
    first_document = observe_document(client, first_run["id"], content_text="first")[
        "document"
    ]
    second_run = create_run(client, endpoint["id"])
    second_document = observe_document(client, second_run["id"], content_text="second")[
        "document"
    ]
    candidate = create_candidate(client, authority["id"])
    create_revision(client, candidate["id"], first_document["id"])

    first = create_evidence(client, first_document["id"])
    second = create_evidence(client, second_document["id"])

    assert first["id"] != second["id"]
    assert first["evidence_hash"] != second["evidence_hash"]
