from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.candidates import Advertisement, AdvertisementRevision
from tests.factories import (
    create_candidate,
    create_discovery_source,
    create_run,
    observe_document,
)


def _candidate_and_document(client: TestClient) -> tuple[dict, dict]:
    authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    return create_candidate(client, authority["id"]), document


def test_legacy_revision_is_explicitly_unsplit_without_fabricated_post(
    client: TestClient, db_session
) -> None:
    candidate, document = _candidate_and_document(client)

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json={
            "source_document_id": document["id"],
            "fields": [
                {
                    "field_path": "recruitment_name",
                    "value_type": "STRING",
                    "value": "Combined recruitment advertisement",
                }
            ],
        },
    )

    assert response.status_code == 201, response.text
    interpretation = response.json()["advertisement_revision"]
    assert interpretation["split_status"] == "LEGACY_UNSPLIT"
    assert interpretation["detected_post_count"] is None
    assert interpretation["posts"] == []
    advertisement = db_session.scalar(select(Advertisement))
    revision = db_session.scalar(select(AdvertisementRevision))
    assert str(advertisement.recruitment_candidate_id) == candidate["id"]
    assert str(revision.candidate_revision_id) == response.json()["id"]


def test_explicit_multi_post_revision_has_independent_post_facts(client: TestClient) -> None:
    candidate, document = _candidate_and_document(client)
    payload = {
        "source_document_id": document["id"],
        "split_status": "EXPLICIT",
        "fields": [
            {
                "field_path": "application.end_date",
                "value_type": "DATE",
                "value": "2026-10-31",
            }
        ],
        "posts": [
            {
                "post_key": "assam_police_grade_iv",
                "ordinal": 1,
                "name": "Grade IV Staff — Assam Police",
                "facts": [
                    {
                        "field_path": "vacancies.total",
                        "value_type": "INTEGER",
                        "value": 181,
                        "source_locator": "pdf:table=1;row=1",
                    }
                ],
            },
            {
                "post_key": "commando_grade_iv",
                "ordinal": 2,
                "name": "Grade IV Staff — Assam Commando Battalions",
                "normalized_name": "grade iv staff assam commando battalions",
                "facts": [
                    {
                        "field_path": "vacancies.total",
                        "value_type": "INTEGER",
                        "value": 6,
                        "source_locator": "pdf:table=1;row=2",
                    }
                ],
            },
        ],
    }

    response = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions", json=payload
    )

    assert response.status_code == 201, response.text
    body = response.json()
    interpretation = body["advertisement_revision"]
    assert interpretation["split_status"] == "EXPLICIT"
    assert interpretation["detected_post_count"] == 2
    assert [post["post_key"] for post in interpretation["posts"]] == [
        "assam_police_grade_iv",
        "commando_grade_iv",
    ]
    assert interpretation["posts"][0]["facts"][0]["fact_key"] == "vacancies.total"
    assert interpretation["posts"][0]["facts"][0]["candidate_field"]["value"] == 181
    assert {field["field_path"] for field in body["fields"]} == {
        "application.end_date",
        "posts.assam_police_grade_iv.vacancies.total",
        "posts.commando_grade_iv.vacancies.total",
    }

    replay = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions", json=payload
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == body["id"]


def test_post_shape_validation_rejects_implicit_or_duplicate_splits(client: TestClient) -> None:
    candidate, document = _candidate_and_document(client)
    post = {
        "post_key": "grade_iv",
        "ordinal": 1,
        "name": "Grade IV",
        "facts": [{"field_path": "vacancies.total", "value_type": "INTEGER", "value": 2}],
    }

    implicit = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json={"source_document_id": document["id"], "posts": [post]},
    )
    assert implicit.status_code == 422

    duplicate = client.post(
        f"/api/v1/recruitment-candidates/{candidate['id']}/revisions",
        json={
            "source_document_id": document["id"],
            "split_status": "EXPLICIT",
            "posts": [post, {**post, "ordinal": 2}],
        },
    )
    assert duplicate.status_code == 422
