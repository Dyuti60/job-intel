import hashlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.models.candidates import CandidateValueType
from app.services.candidate_values import compute_revision_hash
from tests.factories import (
    create_candidate,
    create_discovery_source,
    create_run,
    observe_document,
    revision_payload,
)


@pytest.mark.parametrize(
    ("value_type", "value", "expected"),
    [
        ("STRING", "Cafe\u0301", "Café"),
        ("INTEGER", 21, 21),
        ("DECIMAL", "100.5000", "100.5"),
        ("BOOLEAN", True, True),
        ("DATE", "2026-09-12", "2026-09-12"),
        ("DATETIME", "2026-09-12T10:00:00+05:30", "2026-09-12T04:30:00Z"),
        (
            "JSON",
            {"posts": [{"vacancies": 2}], "active": True},
            {"active": True, "posts": [{"vacancies": 2}]},
        ),
        ("NULL", None, None),
    ],
)
def test_typed_candidate_field_round_trip(
    client: TestClient,
    value_type: str,
    value,
    expected,
) -> None:
    authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    candidate = create_candidate(client, authority["id"])
    fields = [
        {
            "field_path": "test.value",
            "value_type": value_type,
            "value": value,
            "raw_value": "original extracted text",
            "source_locator": "page=1",
        }
    ]

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(document["id"], fields=fields),
    )

    assert response.status_code == 201, response.text
    assert response.json()["fields"][0]["value"] == expected
    assert response.json()["fields"][0]["raw_value"] == "original extracted text"


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        ("INTEGER", True),
        ("DECIMAL", 1.25),
        ("BOOLEAN", "true"),
        ("DATE", "12/09/2026"),
        ("DATETIME", "2026-09-12T10:00:00"),
        ("NULL", "not-null"),
    ],
)
def test_invalid_typed_candidate_value_is_rejected(
    client: TestClient, value_type: str, value
) -> None:
    authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    candidate = create_candidate(client, authority["id"])

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json=revision_payload(
            document["id"],
            fields=[
                {
                    "field_path": "invalid.value",
                    "value_type": value_type,
                    "value": value,
                }
            ],
        ),
    )

    assert response.status_code == 422


def revision_hash(
    document_id: uuid.UUID,
    fields: list[tuple[str, CandidateValueType, object]],
    document_hash: str = "a" * 64,
) -> str:
    return compute_revision_hash(
        source_document_id=document_id,
        source_document_content_hash=document_hash,
        fields=fields,
    )


def test_same_canonical_input_produces_same_revision_hash() -> None:
    document_id = uuid.uuid4()
    fields = [("vacancies.total", CandidateValueType.INTEGER, 42)]

    assert revision_hash(document_id, fields) == revision_hash(document_id, fields)


def test_field_order_does_not_affect_revision_hash() -> None:
    document_id = uuid.uuid4()
    first = [
        ("vacancies.total", CandidateValueType.INTEGER, 42),
        ("recruitment_name", CandidateValueType.STRING, "Recruitment"),
    ]

    assert revision_hash(document_id, first) == revision_hash(
        document_id, list(reversed(first))
    )


def test_changed_structured_value_changes_revision_hash() -> None:
    document_id = uuid.uuid4()

    assert revision_hash(
        document_id, [("vacancies.total", CandidateValueType.INTEGER, 42)]
    ) != revision_hash(
        document_id, [("vacancies.total", CandidateValueType.INTEGER, 43)]
    )


def test_changed_source_document_identity_changes_revision_hash() -> None:
    fields = [("vacancies.total", CandidateValueType.INTEGER, 42)]

    assert revision_hash(uuid.uuid4(), fields) != revision_hash(uuid.uuid4(), fields)


def test_volatile_metadata_is_absent_from_revision_hash() -> None:
    document_id = uuid.uuid4()
    fields = [("notification.date", CandidateValueType.DATE, "2026-09-12")]

    first_hash = revision_hash(document_id, fields)
    second_hash = revision_hash(document_id, fields)

    assert first_hash == second_hash


def test_legacy_revision_hash_remains_byte_compatible_with_pre_post_domain() -> None:
    document_id = uuid.UUID("10000000-0000-0000-0000-000000000001")
    fields = [("vacancies.total", CandidateValueType.INTEGER, 42)]
    legacy_payload = {
        "source_document": {"id": str(document_id), "content_hash": "a" * 64},
        "fields": [
            {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 42}
        ],
    }
    expected = hashlib.sha256(
        json.dumps(
            legacy_payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert revision_hash(document_id, fields) == expected


def test_post_manifest_and_ambiguous_interpretation_change_revision_identity() -> None:
    document_id = uuid.uuid4()
    fields = [("posts.grade_iv.vacancies.total", CandidateValueType.INTEGER, 42)]
    common = {
        "source_document_id": document_id,
        "source_document_content_hash": "a" * 64,
        "fields": fields,
    }

    explicit = compute_revision_hash(
        **common,
        posts=[
            {
                "post_key": "grade_iv",
                "ordinal": 1,
                "name": "Grade IV",
                "normalized_name": "grade iv",
                "fact_keys": ["vacancies.total"],
            }
        ],
    )
    renamed = compute_revision_hash(
        **common,
        posts=[
            {
                "post_key": "grade_iv",
                "ordinal": 1,
                "name": "Grade-IV Staff",
                "normalized_name": "grade-iv staff",
                "fact_keys": ["vacancies.total"],
            }
        ],
    )
    ambiguous = compute_revision_hash(
        **common, interpretation={"split_status": "AMBIGUOUS"}
    )

    assert len({explicit, renamed, ambiguous}) == 3
