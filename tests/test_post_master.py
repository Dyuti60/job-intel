import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.master import MasterPost, MasterPostFact
from app.models.review import ReviewItem
from tests.factories import (
    add_verification_assessment,
    complete_verification_run,
    create_candidate,
    create_discovery_source,
    create_evidence,
    create_field_verification,
    create_revision,
    create_run,
    create_verification_run,
    finalize_field_verification,
    observe_document,
    start_verification_run,
)


def _explicit_two_post_run(client) -> dict:
    authority, endpoint = create_discovery_source(client)
    discovery = create_run(client, endpoint["id"])
    document = observe_document(client, discovery["id"])["document"]
    candidate = create_candidate(
        client,
        authority["id"],
        candidate_key="APSC_TWO_POSTS",
        display_name="Two Post Recruitment",
    )
    revision = create_revision(
        client,
        candidate["id"],
        document["id"],
        split_status="EXPLICIT",
        fields=[
            {
                "field_path": "recruitment_name",
                "value_type": "STRING",
                "value": "Two Post Recruitment",
                "source_locator": "pdf:page=1",
            },
            {"field_path": "application.start_date", "value_type": "DATE", "value": "2026-09-01"},
            {"field_path": "application.end_date", "value_type": "DATE", "value": "2026-09-30"},
        ],
        posts=[
            {
                "post_key": "valid_post",
                "ordinal": 1,
                "name": "Valid Post",
                "source_locator": "pdf:table=1;row=1",
                "facts": [
                    {"field_path": "name", "value_type": "STRING", "value": "Valid Post"},
                    {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 10},
                    {"field_path": "age.minimum", "value_type": "INTEGER", "value": 21},
                    {"field_path": "age.maximum", "value_type": "INTEGER", "value": 38},
                    {
                        "field_path": "age.reference_date",
                        "value_type": "DATE",
                        "value": "2026-01-01",
                    },
                    {
                        "field_path": "qualification.minimum",
                        "value_type": "STRING",
                        "value": "Bachelor Degree",
                    },
                    {
                        "field_path": "domicile.requirement",
                        "value_type": "STRING",
                        "value": "Permanent resident of Assam",
                    },
                    {
                        "field_path": "experience.minimum_months",
                        "value_type": "INTEGER",
                        "value": 12,
                    },
                ],
            },
            {
                "post_key": "conflicted_post",
                "ordinal": 2,
                "name": "Conflicted Post",
                "source_locator": "pdf:table=1;row=2",
                "facts": [
                    {
                        "field_path": "name",
                        "value_type": "STRING",
                        "value": "Conflicted Post",
                    },
                    {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 20},
                    {"field_path": "age.minimum", "value_type": "INTEGER", "value": 21},
                    {
                        "field_path": "qualification.minimum",
                        "value_type": "STRING",
                        "value": "Bachelor Degree",
                    },
                ],
            },
        ],
    )
    ready = client.patch(
        f"/api/v1/recruitment-candidates/{candidate['id']}",
        json={"status": "READY_FOR_VERIFICATION"},
    )
    assert ready.status_code == 200
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    for field in revision["fields"]:
        verification = create_field_verification(client, run["id"], field["id"])
        evidence = create_evidence(
            client,
            document["id"],
            excerpt=f"{field['field_path']}={field['value']}",
            source_locator=field["source_locator"] or "pdf:table=1",
        )
        conflicted = field["field_path"] == "posts.conflicted_post.vacancies.total"
        add_verification_assessment(
            client,
            verification["id"],
            evidence["id"],
            "CONTRADICTS" if conflicted else "SUPPORTS",
            asserted_value=99 if conflicted else field["value"],
            asserted_value_type=field["value_type"],
        )
        finalize_field_verification(client, verification["id"])
    complete_verification_run(client, run["id"])
    return run


def test_rejected_post_does_not_block_valid_sibling_master(client, db_session) -> None:
    run = _explicit_two_post_run(client)
    confidence = client.post(f"/api/v1/verification-runs/{run['id']}/confidence-v2").json()
    routing = client.post(f"/api/v1/revision-confidence/{confidence['id']}/review-routing").json()
    assert routing["review_required"] is True
    assert routing["field_routes"][0]["field_path"] == ("posts.conflicted_post.vacancies.total")
    case = client.post(
        "/api/v1/review-cases",
        json={"revision_confidence_assessment_id": confidence["id"]},
    ).json()
    assert case["review_routing_assessment_id"] == routing["id"]
    assert len(case["items"]) == 1
    page = client.get(f"/review/cases/{case['id']}")
    assert page.status_code == 200
    assert "Conflicted Post" in page.text
    assert "Valid Post" not in page.text
    started = client.post(f"/api/v1/review-cases/{case['id']}/start").json()
    decision = client.post(
        f"/api/v1/review-items/{started['items'][0]['id']}/decision",
        json={
            "decision": "REJECT",
            "reviewer_identifier": "post-reviewer",
            "decision_note": "The official total conflicts; exclude only this Post.",
        },
    )
    assert decision.status_code == 201

    first = client.post(
        "/api/v1/recruitment-master/publish",
        json={"revision_confidence_assessment_id": confidence["id"]},
    )
    replay = client.post(
        "/api/v1/recruitment-master/publish",
        json={"revision_confidence_assessment_id": confidence["id"]},
    )
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["master_revision"]["id"] == first.json()["master_revision"]["id"]
    revision = first.json()["master_revision"]
    assert [post["post_key"] for post in revision["posts"]] == ["valid_post"]
    expected_post_facts = {
        "age.maximum",
        "age.minimum",
        "age.reference_date",
        "domicile.requirement",
        "experience.minimum_months",
        "name",
        "qualification.minimum",
        "vacancies.total",
    }
    assert {fact["fact_key"] for fact in revision["posts"][0]["facts"]} == expected_post_facts
    assert {field["field_path"] for field in revision["fields"]} == {
        "recruitment_name",
        "application.start_date",
        "application.end_date",
    } | {f"posts.valid_post.{fact}" for fact in expected_post_facts}
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 1
    assert db_session.scalar(select(func.count()).select_from(MasterPostFact)) == 8
    fact = db_session.scalar(select(MasterPostFact))
    assert fact is not None
    fact.master_revision_id = uuid.uuid4()
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_post_publication_fails_closed_for_tampered_routing_review_snapshot(
    client, db_session
) -> None:
    run = _explicit_two_post_run(client)
    confidence = client.post(f"/api/v1/verification-runs/{run['id']}/confidence-v2").json()
    client.post(f"/api/v1/revision-confidence/{confidence['id']}/review-routing")
    case = client.post(
        "/api/v1/review-cases",
        json={"revision_confidence_assessment_id": confidence["id"]},
    ).json()
    client.post(f"/api/v1/review-cases/{case['id']}/start")
    decision = client.post(
        f"/api/v1/review-items/{case['items'][0]['id']}/decision",
        json={
            "decision": "REJECT",
            "reviewer_identifier": "post-reviewer",
            "decision_note": "Exclude the conflicted Post.",
        },
    )
    assert decision.status_code == 201

    item = db_session.scalar(
        select(ReviewItem).where(ReviewItem.id == uuid.UUID(case["items"][0]["id"]))
    )
    assert item is not None
    item.review_reason_codes_snapshot = ["SOURCE_CONFLICT"]
    db_session.commit()

    response = client.post(
        "/api/v1/recruitment-master/publish",
        json={"revision_confidence_assessment_id": confidence["id"]},
    )
    assert response.status_code == 409
    assert "item snapshot fails integrity validation" in response.json()["detail"]
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 0
