import json
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.models.candidates import AdvertisementSplitStatus, RecruitmentCandidateRevision
from app.models.master import MasterPost
from app.models.review import ReviewCaseStatus, ReviewDecision
from app.services.post_identity import canonical_post_name, stable_post_key
from app.services.review import ReviewService
from app.services.verification_worker import VerificationWorkerService
from sources.post_structure import structure_posts
from tests.factories import create_revision
from tests.test_review_api import build_review_graph


def test_shared_single_post_grammar_and_identity():
    title = "Advertisement for 48 posts of Sub Inspector (UB) in Assam Police"
    posts, status, _, warnings = structure_posts(title, title)
    assert status == AdvertisementSplitStatus.EXPLICIT
    assert warnings == ()
    assert len(posts) == 1
    assert posts[0].name == "Sub Inspector (UB) – Assam Police"
    assert next(f.value for f in posts[0].facts if f.field_path == "vacancies.total") == 48
    assert stable_post_key("Driver", "Forest Department") != stable_post_key(
        "Driver", "Assam Police"
    )
    assert (
        canonical_post_name("Driver - Forest Department", "Forest Department")
        == "Driver – Forest Department"
    )
    assert canonical_post_name("Research Assistant") == "Research Assistant"


@pytest.mark.parametrize("status", ["LEGACY_UNSPLIT", "AMBIGUOUS"])
def test_human_structure_preserves_history_and_uses_existing_publication(
    client, db_session, status
):
    graph = build_review_graph(
        client,
        suffix="MANUAL_" + status,
        modes={"application.end_date": "auth_support_secondary_conflict"},
    )
    if status == "AMBIGUOUS":
        revision = create_revision(
            client,
            graph["candidate"]["id"],
            graph["document"]["id"],
            split_status="AMBIGUOUS",
            split_note="Official vacancy ownership uncertain",
            fields=[
                {"field_path": "application.end_date", "value_type": "DATE", "value": "2026-10-20"}
            ],
        )
        result = VerificationWorkerService(db_session).process_revision(UUID(revision["id"]))
        db_session.commit()
        graph["revision"] = revision
        graph["case"] = client.get(f"/api/v1/review-cases/{result.review_case_id}").json()
    original_id = graph["revision"]["id"]
    original = db_session.get(RecruitmentCandidateRevision, UUID(original_id))
    initial_revisions = db_session.scalar(
        select(func.count()).select_from(RecruitmentCandidateRevision)
    )
    before = client.get(f"/api/v1/candidate-revisions/{original_id}").json()
    case_id = graph["case"]["id"]
    page = client.get(f"/review/cases/{case_id}")
    assert "Manual Post Builder" in page.text
    assert "Add Post" in page.text and "Remove Post" in page.text
    payload = {
        "post_title": ["Research Assistant", "Research Assistant"],
        "post_organisation": ["Labour Welfare Department", "Forest Department"],
        "post_vacancies": ["7", "5"],
        "structure_comment": "Confirmed individual Posts against official source",
    }
    missing = client.post(
        f"/review/cases/{case_id}/structure", data={**payload, "structure_comment": ""}
    )
    assert missing.status_code == 400
    assert "Research Assistant" in missing.text
    assert (
        db_session.scalar(select(func.count()).select_from(RecruitmentCandidateRevision))
        == initial_revisions
    )
    response = client.post(f"/review/cases/{case_id}/structure", data=payload)
    assert response.status_code == 200, response.text
    assert "Structure approved" in response.text
    new_case_id = response.url.path.split("/")[-1]
    new_case = client.get(f"/api/v1/review-cases/{new_case_id}").json()
    revision = db_session.get(RecruitmentCandidateRevision, UUID(new_case["candidate_revision_id"]))
    assert revision.id != original.id
    assert len(revision.advertisement_revision.posts) == 2
    audit = json.loads(revision.extraction_note)
    assert audit["original_revision"] == original_id
    assert audit["comment"] == payload["structure_comment"]
    assert audit["reviewer"] and audit["approved_at"]
    assert ReviewService(db_session).get_case(UUID(case_id)).status == ReviewCaseStatus.CANCELLED
    assert client.get(f"/api/v1/candidate-revisions/{original_id}").json() == before
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 0
    posts = revision.advertisement_revision.posts
    blocked = client.post(
        f"/review/cases/{new_case_id}/publish", data={"post": posts[0].post_key}
    )
    assert "error=" in blocked.history[0].headers["location"]
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 0
    first = client.post(
        f"/review/cases/{new_case_id}/quick-publish",
        data={"post": posts[0].post_key, "comment": "Reviewed remaining shared requirements"},
    )
    assert "View Published Job" in first.text, first.text
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 1
    assert (
        "READY TO PUBLISH"
        in client.get(f"/review/cases/{new_case_id}?post={posts[1].post_key}").text
    )
    second = client.post(f"/review/cases/{new_case_id}/publish", data={"post": posts[1].post_key})
    assert "View Published Job" in second.text
    public = client.get("/api/public/v1/recruitments?as_of=2026-09-20").json()["items"]
    assert len(public) == 2
    assert {item["display_name"] for item in public} == {p.name for p in posts}
    assert {item["vacancies_total"] for item in public} == {7, 5}
    decision_count = db_session.scalar(select(func.count()).select_from(ReviewDecision))
    replay = client.post(f"/review/cases/{case_id}/structure", data=payload)
    assert replay.status_code == 200
    assert (
        db_session.scalar(select(func.count()).select_from(RecruitmentCandidateRevision))
        == initial_revisions + 1
    )
    assert db_session.scalar(select(func.count()).select_from(ReviewDecision)) == decision_count
    assert client.get(f"/review/cases/{case_id}/structure").status_code == 405
