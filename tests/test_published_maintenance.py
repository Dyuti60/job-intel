"""Published maintenance uses current Master data and immutable correction history."""

from uuid import UUID

from sqlalchemy import func, select

from app.models.candidates import RecruitmentCandidateRevision
from app.models.master import (
    MasterChange,
    MasterPost,
    MasterPublicationEvent,
    RecruitmentMaster,
    RecruitmentMasterRevision,
)
from app.models.review import ReviewCase, ReviewDecision
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
from tests.test_public_recruitments_api import _published
from tests.test_review_web import _three_post_review_graph


def test_auto_published_view_and_immutable_republish(client, db_session):
    graph = _published(client, "MAINTENANCE", end="2026-10-31", vacancies=42)
    master_id = graph["publication"]["master"]["id"]
    before = db_session.get(
        RecruitmentMasterRevision, UUID(graph["publication"]["master_revision"]["id"])
    )
    assert before.publication_path.value == "VERIFIED_NO_REVIEW"
    assert db_session.scalar(select(func.count()).select_from(ReviewCase)) == 0

    queue = client.get("/review")
    assert 'href="/review?view=AUTO_PUBLISHED"' in queue.text
    assert 'href="/review?view=HUMAN_PUBLISHED"' in queue.text
    auto = client.get("/review?view=AUTO_PUBLISHED")
    assert auto.status_code == 200
    assert graph["candidate"]["display_name"] in auto.text
    assert "Edit / Inspect" in auto.text
    assert db_session.scalar(select(func.count()).select_from(ReviewCase)) == 0

    editor = client.get(f"/review/published/{master_id}")
    assert editor.status_code == 200
    assert 'name="field.application.end_date"' in editor.text
    assert graph["document"]["document_url"] in editor.text
    assert client.get(f"/review/published/{master_id}/republish").status_code == 405

    missing_comment = client.post(
        f"/review/published/{master_id}/republish",
        data={
            "master_revision_id": str(before.id),
            "field.application.end_date": "2026-11-30",
        },
        follow_redirects=False,
    )
    assert "error=" in missing_comment.headers["location"]
    assert db_session.scalar(select(func.count()).select_from(RecruitmentCandidateRevision)) == 1

    correction = client.post(
        f"/review/published/{master_id}/republish",
        data={
            "master_revision_id": str(before.id),
            "field.application.end_date": "2026-11-30",
            "field.application.mode": "Online",
            "comment": "Checked dates and mode against the official notice.",
        },
        follow_redirects=False,
    )
    assert "message=" in correction.headers["location"], correction.headers["location"]
    assert db_session.scalar(select(func.count()).select_from(RecruitmentCandidateRevision)) == 2
    current = db_session.get(type(before.recruitment_master), UUID(master_id))
    db_session.refresh(current)
    assert current.current_revision_id != before.id
    assert db_session.get(RecruitmentMasterRevision, before.id).id == before.id
    assert current.current_revision.publication_path.value.startswith("HUMAN_")
    assert db_session.scalar(select(func.count()).select_from(ReviewDecision)) >= 1
    assert db_session.scalar(select(func.count()).select_from(MasterPublicationEvent)) == 2
    changed_date = db_session.scalar(
        select(MasterChange).where(
            MasterChange.to_master_revision_id == current.current_revision_id,
            MasterChange.field_path == "application.end_date",
        )
    )
    assert changed_date.old_value == "2026-10-31"
    assert changed_date.new_value == "2026-11-30"
    assert client.get(f"/jobs/{master_id}", params={"as_of": "2026-10-01"}).status_code == 200
    assert (
        "30 November 2026" in client.get(f"/jobs/{master_id}", params={"as_of": "2026-10-01"}).text
    )
    assert "Human published" in client.get("/review?view=HUMAN_PUBLISHED").text
    assert "No published jobs" in client.get("/review?view=AUTO_PUBLISHED").text


def test_human_published_post_edit_preserves_public_identity_and_siblings(client, db_session):
    graph = _three_post_review_graph(client)
    case_id = graph["case"]["id"]
    approved = client.post(
        f"/review/cases/{case_id}/quick-publish",
        data={
            "post": "assam_police",
            "comment": "Checked official advertisement",
        },
    )
    assert approved.status_code == 200
    original = db_session.scalar(select(MasterPost).where(MasterPost.post_key == "assam_police"))
    assert original is not None
    public_id = original.public_id
    current = db_session.get(RecruitmentMasterRevision, original.master_revision_id)
    assert "Human published" in client.get("/review?view=HUMAN_PUBLISHED").text
    assert str(public_id) in client.get("/review?view=HUMAN_PUBLISHED").text
    editor = client.get(f"/review/published/{public_id}")
    assert editor.status_code == 200
    assert 'value="181"' in editor.text
    assert 'name="field.posts.assam_police.vacancies.total"' in editor.text

    invalid = client.post(
        f"/review/published/{public_id}/republish",
        data={
            "master_revision_id": str(current.id),
            "field.posts.new_post.vacancies.total": "1",
            "comment": "Unsafe structural edit",
        },
        follow_redirects=False,
    )
    assert "error=" in invalid.headers["location"]
    assert db_session.scalar(select(func.count()).select_from(RecruitmentCandidateRevision)) == 1

    result = client.post(
        f"/review/published/{public_id}/republish",
        data={
            "master_revision_id": str(current.id),
            "field.posts.assam_police.vacancies.total": "180",
            "field.posts.assam_police.physical.criteria": '{"height": "160 cm"}',
            "comment": "Corrected Assam Police values against the official notice.",
        },
        follow_redirects=False,
    )
    assert "message=" in result.headers["location"], result.headers["location"]
    master = db_session.get(RecruitmentMaster, current.recruitment_master_id)
    db_session.refresh(master)
    assert master.current_revision_id != current.id
    assert db_session.get(RecruitmentMasterRevision, current.id) is not None
    latest = db_session.scalar(
        select(MasterPost).where(MasterPost.master_revision_id == master.current_revision_id)
    )
    assert latest.public_id == public_id
    assert latest.post_key == "assam_police"
    assert db_session.scalar(select(func.count()).select_from(MasterPost)) == 2
    public = client.get("/api/public/v1/recruitments", params={"as_of": "2026-09-22"})
    assert public.status_code == 200
    assert public.json()["total"] == 1
    assert public.json()["items"][0]["id"] == str(public_id)
    detail = client.get(f"/jobs/{public_id}", params={"as_of": "2026-09-22"})
    assert "180" in detail.text
    assert "160 cm" in detail.text
    replay = client.post(
        f"/review/published/{public_id}/republish",
        data={
            "master_revision_id": str(master.current_revision_id),
            "field.posts.assam_police.vacancies.total": "180",
            "comment": "Repeat request",
        },
        follow_redirects=False,
    )
    assert "No+changes" in replay.headers["location"]
    assert db_session.scalar(select(func.count()).select_from(RecruitmentCandidateRevision)) == 2


def test_missing_supported_facts_can_be_added_to_unsplit_publication(client, db_session):
    graph = _published(client, "MISSING", end=None, vacancies=None)
    master_id = graph["publication"]["master"]["id"]
    revision_id = graph["publication"]["master_revision"]["id"]
    editor = client.get(f"/review/published/{master_id}")
    assert "PARTIAL" in editor.text
    assert 'name="field.vacancies.total"' in editor.text
    assert 'name="field.qualification.minimum"' in editor.text
    result = client.post(
        f"/review/published/{master_id}/republish",
        data={
            "master_revision_id": revision_id,
            "field.vacancies.total": "48",
            "field.application.end_date": "2026-10-31",
            "field.qualification.minimum": "Recognised bachelor degree",
            "comment": "Checked missing facts against the official advertisement.",
        },
        follow_redirects=False,
    )
    assert "message=" in result.headers["location"], result.headers["location"]
    listing = client.get("/api/public/v1/recruitments", params={"as_of": "2026-10-01"})
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == master_id
    assert listing.json()["items"][0]["vacancies_total"] == 48
    assert (
        "Recognised bachelor degree"
        in client.get(f"/jobs/{master_id}", params={"as_of": "2026-10-01"}).text
    )
    decisions = db_session.scalars(select(ReviewDecision)).all()
    assert decisions
    assert all(
        decision.decision_note == "Checked missing facts against the official advertisement."
        for decision in decisions
    )
    assert all(decision.reviewer_identifier == "local-review-ui" for decision in decisions)


def test_auto_published_explicit_advertisement_has_post_rows_without_parent(client, db_session):
    authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    candidate = create_candidate(
        client,
        authority["id"],
        candidate_key="MAINT_TWO_POSTS",
        display_name="Two-role official advertisement",
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
                "value": "Two-role official advertisement",
            }
        ],
        posts=[
            {
                "post_key": key,
                "ordinal": ordinal,
                "name": title,
                "facts": [
                    {"field_path": "name", "value_type": "STRING", "value": title},
                    {"field_path": "vacancies.total", "value_type": "INTEGER", "value": count},
                ],
            }
            for ordinal, (key, title, count) in enumerate(
                (
                    ("cook_police", "Cook - Assam Police", 115),
                    ("cook_dgcd", "Cook - DGCD", 27),
                ),
                1,
            )
        ],
    )
    client.patch(
        f"/api/v1/recruitment-candidates/{candidate['id']}",
        json={"status": "READY_FOR_VERIFICATION"},
    )
    verification_run = create_verification_run(client, revision["id"])
    start_verification_run(client, verification_run["id"])
    for field in revision["fields"]:
        verification = create_field_verification(client, verification_run["id"], field["id"])
        evidence = create_evidence(
            client, document["id"], excerpt=f"Official {field['field_path']}: {field['value']}"
        )
        add_verification_assessment(
            client,
            verification["id"],
            evidence["id"],
            "SUPPORTS",
            asserted_value=field["value"],
            asserted_value_type=field["value_type"],
        )
        finalize_field_verification(client, verification["id"])
    complete_verification_run(client, verification_run["id"])
    confidence = client.post(
        f"/api/v1/verification-runs/{verification_run['id']}/confidence-v2"
    ).json()
    publication = client.post(
        "/api/v1/recruitment-master/publish",
        json={"revision_confidence_assessment_id": confidence["id"]},
    )
    assert publication.status_code == 201, publication.text
    assert db_session.scalar(select(func.count()).select_from(ReviewCase)) == 0
    auto = client.get("/review?view=AUTO_PUBLISHED")
    assert "Cook - Assam Police" in auto.text
    assert "Cook - DGCD" in auto.text
    assert auto.text.count("Edit / Inspect") == 2
    assert "2</strong><span>Auto published" in auto.text
    assert "Two-role official advertisement</strong>" not in auto.text


def test_organisation_addition_requires_base_title_and_keeps_canonical_name(client, db_session):
    graph = _three_post_review_graph(client)
    client.post(
        f"/review/cases/{graph['case']['id']}/quick-publish",
        data={
            "post": "assam_police",
            "comment": "Checked source",
        },
    )
    post = db_session.scalar(select(MasterPost).where(MasterPost.post_key == "assam_police"))
    assert post is not None
    previous_revision = post.master_revision_id
    blocked = client.post(
        f"/review/published/{post.public_id}/republish",
        data={
            "master_revision_id": str(previous_revision),
            "field.posts.assam_police.organisation.name": "Assam Police",
            "comment": "Added unit from source",
        },
        follow_redirects=False,
    )
    assert "error=" in blocked.headers["location"]
    assert db_session.scalar(select(func.count()).select_from(RecruitmentCandidateRevision)) == 1
    corrected = client.post(
        f"/review/published/{post.public_id}/republish",
        data={
            "master_revision_id": str(previous_revision),
            "field.posts.assam_police.name": "Grade IV Staff",
            "field.posts.assam_police.organisation.name": "Assam Police",
            "comment": "Confirmed canonical title and unit from source",
        },
        follow_redirects=False,
    )
    assert "message=" in corrected.headers["location"], corrected.headers["location"]
    master = db_session.get(RecruitmentMaster, post.master_revision.recruitment_master_id)
    db_session.refresh(master)
    current_post = db_session.scalar(
        select(MasterPost).where(MasterPost.master_revision_id == master.current_revision_id)
    )
    assert current_post.public_id == post.public_id
    assert current_post.name == "Grade IV Staff – Assam Police"
