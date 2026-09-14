from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.review import ReviewCase, ReviewDecision, ReviewItem
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
from tests.test_post_master import _explicit_two_post_run
from tests.test_review_api import _field_item, build_review_graph


def _web_graph(client: TestClient, suffix: str) -> dict:
    graph = build_review_graph(
        client,
        suffix=suffix,
        modes={"application.end_date": "auth_support_secondary_conflict"},
    )
    field = graph["revision"]["fields"][0]
    extraction = graph["evidence"][0]
    linked = client.post(
        f"/api/v1/candidate-fields/{field['id']}/evidence/{extraction['id']}"
    )
    assert linked.status_code == 201, linked.text
    return graph


def _three_post_review_graph(client: TestClient) -> dict:
    authority, endpoint = create_discovery_source(client)
    discovery = create_run(client, endpoint["id"])
    document = observe_document(client, discovery["id"])["document"]
    candidate = create_candidate(
        client,
        authority["id"],
        candidate_key="REVIEW_THREE_POSTS",
        display_name="SLPRB Grade IV Advertisement",
    )
    posts = (
        ("assam_police", "Grade IV Staff - Assam Police", 181),
        (
            "assam_commando_battalions",
            "Grade IV Staff - Assam Commando Battalions",
            6,
        ),
        ("dgcd_cghg", "Grade IV Staff - DGCD & CGHG", 69),
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
                "value": "SLPRB Grade IV Advertisement",
            },
            {
                "field_path": "application.end_date",
                "value_type": "DATE",
                "value": "2026-10-20",
            },
        ],
        posts=[
            {
                "post_key": key,
                "ordinal": ordinal,
                "name": name,
                "facts": [
                    {"field_path": "name", "value_type": "STRING", "value": name},
                    {
                        "field_path": "vacancies.total",
                        "value_type": "INTEGER",
                        "value": vacancies,
                    },
                ],
            }
            for ordinal, (key, name, vacancies) in enumerate(posts, start=1)
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
            excerpt=f"Official evidence for {field['field_path']}",
        )
        needs_review = field["field_path"] == "application.end_date" or (
            field["field_path"].startswith("posts.")
            and field["field_path"].endswith("vacancies.total")
        )
        add_verification_assessment(
            client,
            verification["id"],
            evidence["id"],
            "CONTRADICTS" if needs_review else "SUPPORTS",
            asserted_value=(999 if field["value_type"] == "INTEGER" else "2026-10-21")
            if needs_review
            else field["value"],
            asserted_value_type=field["value_type"],
        )
        finalize_field_verification(client, verification["id"])
    complete_verification_run(client, run["id"])
    confidence = client.post(f"/api/v1/verification-runs/{run['id']}/confidence-v2").json()
    routing = client.post(
        f"/api/v1/revision-confidence/{confidence['id']}/review-routing"
    )
    assert routing.status_code == 201
    case = client.post(
        "/api/v1/review-cases",
        json={"revision_confidence_assessment_id": confidence["id"]},
    ).json()
    return {"candidate": candidate, "case": case, "posts": posts}


def _start_web_case(client: TestClient, case_id: str) -> None:
    response = client.post(f"/review/cases/{case_id}/start", follow_redirects=False)
    assert response.status_code == 303


def _decision(
    client: TestClient,
    item_id: str,
    decision: str,
    **values: str,
):
    payload = {
        "decision": decision,
        "decision_note": "Reviewed against the displayed official evidence.",
        **values,
    }
    return client.post(
        f"/review/items/{item_id}/decision",
        data=payload,
        follow_redirects=False,
    )


def _submit_post(
    client: TestClient,
    case: dict,
    post_key: str | None,
    *,
    final_action: str,
    reject_post_item: bool = False,
    comment: str = "Reviewed together against the retained official evidence.",
    omit_item_id: str | None = None,
):
    data = {"comment": comment, "final_action": final_action}
    if post_key is not None:
        data["post"] = post_key
    for item in case["items"]:
        path = item["field_path_snapshot"]
        belongs = (
            post_key is None
            or path is None
            or not path.startswith("posts.")
            or path.startswith(f"posts.{post_key}.")
        )
        if item["status"] != "PENDING" or not belongs or item["id"] == omit_item_id:
            continue
        decision = "APPROVE_AS_IS"
        if reject_post_item and path is not None and path.startswith(f"posts.{post_key}."):
            decision = "REJECT"
        data[f"item_{item['id']}"] = decision
    return client.post(
        f"/review/cases/{case['id']}/submit",
        data=data,
        follow_redirects=False,
    )


def test_queue_page_lists_counts_orders_and_filters(client: TestClient) -> None:
    high = build_review_graph(
        client,
        suffix="WEB_QUEUE_HIGH",
        modes={"application.end_date": "secondary_support"},
    )["case"]
    normal = build_review_graph(
        client,
        suffix="WEB_QUEUE_NORMAL",
        fields=[{"field_path": "description.summary", "value_type": "STRING", "value": "x"}],
    )["case"]
    assert high is not None and normal is not None

    page = client.get("/review")
    filtered = client.get("/review", params={"status": "QUEUED", "priority": "HIGH"})

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "Human Review Queue" in page.text
    assert "Queued" in page.text and "Critical active" in page.text and "In review" in page.text
    assert page.text.index("WEB_QUEUE_HIGH_RECRUITMENT") < page.text.index(
        "WEB_QUEUE_NORMAL_RECRUITMENT"
    )
    assert high["id"] in filtered.text
    assert normal["id"] not in filtered.text


def test_case_page_composes_candidate_confidence_and_evidence_safely(
    client: TestClient,
) -> None:
    graph = _web_graph(client, "WEB_DETAIL")
    field = graph["revision"]["fields"][0]
    unsafe = create_evidence(
        client,
        graph["document"]["id"],
        excerpt='<script>alert("unsafe")</script>',
        context="Context around deadline",
        source_locator="page=4;section=Dates",
    )
    link = client.post(f"/api/v1/candidate-fields/{field['id']}/evidence/{unsafe['id']}")
    assert link.status_code == 201

    page = client.get(f"/review/cases/{graph['case']['id']}")

    assert page.status_code == 200
    for expected in [
        graph["candidate"]["display_name"],
        "Revision confidence",
        "CRITICAL_FIELD_BELOW_THRESHOLD",
        "Confidence component breakdown",
        "Extraction Evidence",
        "page=4;section=Dates",
        "AUTHORITATIVE_OFFICIAL",
        "Verification Evidence Assessments",
        "SUPPORTS",
        "CONTRADICTS",
        "2026-10-25",
        graph["document"]["document_url"],
    ]:
        assert expected in page.text
    assert "<script>alert" not in page.text
    assert "&lt;script&gt;alert" in page.text
    assert 'target="_blank"' in page.text
    assert 'rel="noopener noreferrer"' in page.text
    assert "<details class=\"evidence-section\">" in page.text
    assert "<summary>View source evidence</summary>" in page.text
    assert "<section class=\"evidence-section\">" not in page.text


def test_review_queue_and_detail_focus_on_exact_post(client: TestClient) -> None:
    run = _explicit_two_post_run(client)
    confidence = client.post(f"/api/v1/verification-runs/{run['id']}/confidence-v2").json()
    client.post(f"/api/v1/revision-confidence/{confidence['id']}/review-routing")
    case = client.post(
        "/api/v1/review-cases",
        json={"revision_confidence_assessment_id": confidence["id"]},
    ).json()

    queue = client.get("/review")
    focused = client.get(f"/review/cases/{case['id']}", params={"post": "conflicted_post"})

    assert "Conflicted Post" in queue.text
    assert "Advertisement: Two Post Recruitment" in queue.text
    assert f"/review/cases/{case['id']}?post=conflicted_post" in queue.text
    assert "Vacancies Total" in queue.text and "20" in queue.text
    assert "Authoritative Conflict" in queue.text
    assert focused.status_code == 200
    assert "<h1>Conflicted Post</h1>" in focused.text
    assert "Post and Advertisement context" in focused.text
    assert "Parent Advertisement" in focused.text
    assert "Two Post Recruitment" in focused.text
    assert "posts.conflicted_post.vacancies.total" in focused.text
    assert "posts.valid_post.vacancies.total" not in focused.text


def test_explicit_three_post_review_is_post_first_when_active_and_resolved(
    client: TestClient,
) -> None:
    graph = _three_post_review_graph(client)
    case = graph["case"]

    active = client.get("/review")

    assert active.status_code == 200
    assert active.text.count('class="case-link"') == 3
    assert "Advertisement-wide review" not in active.text
    for _key, name, vacancies in graph["posts"]:
        rendered_name = name.replace("&", "&amp;")
        assert f">{rendered_name}</a>" in active.text
        entry = active.text.split(f">{rendered_name}</a>", 1)[1].split("</tr>", 1)[0]
        assert "Vacancies Total" in entry
        assert f"</strong> {vacancies}</small>" in entry
        assert "Advertisement: SLPRB Grade IV Advertisement" in entry

    police = client.get(
        f"/review/cases/{case['id']}", params={"post": "assam_police"}
    )
    assert "<h1>Grade IV Staff - Assam Police</h1>" in police.text
    assert "Shared Advertisement review items" in police.text
    assert "application.end_date" in police.text
    assert "posts.assam_police.vacancies.total" in police.text
    assert "posts.assam_commando_battalions.vacancies.total" not in police.text
    assert "posts.dgcd_cghg.vacancies.total" not in police.text
    assert 'name="post" value="assam_police"' not in police.text

    start = client.post(
        f"/review/cases/{case['id']}/start",
        params={"post": "assam_police"},
        follow_redirects=False,
    )
    assert "post=assam_police" in start.headers["location"]
    started_page = client.get(start.headers["location"])
    assert 'name="post" value="assam_police"' in started_page.text
    started = client.get(f"/api/v1/review-cases/{case['id']}").json()
    for item in started["items"]:
        response = client.post(
            f"/api/v1/review-items/{item['id']}/decision",
            json={
                "decision": "APPROVE_AS_IS",
                "reviewer_identifier": "post-first-reviewer",
                "decision_note": "Approved against the retained source evidence.",
            },
        )
        assert response.status_code == 201

    resolved = client.get("/review", params={"status": "RESOLVED"})
    resolved_police = client.get(
        f"/review/cases/{case['id']}", params={"post": "assam_police"}
    )
    assert resolved.text.count('class="case-link"') == 3
    assert "Advertisement-wide review" not in resolved.text
    assert all(
        f">{name.replace('&', '&amp;')}</a>" in resolved.text
        for _key, name, _vacancies in graph["posts"]
    )
    assert "posts.assam_police.vacancies.total" in resolved_police.text
    assert "posts.assam_commando_battalions.vacancies.total" not in resolved_police.text
    assert "posts.dgcd_cghg.vacancies.total" not in resolved_police.text


def test_legacy_unsplit_review_retains_one_advertisement_entry(client: TestClient) -> None:
    graph = _web_graph(client, "WEB_LEGACY_UNSPLIT")

    queue = client.get("/review")

    assert queue.text.count('class="case-link"') == 1
    assert f">{graph['candidate']['display_name']}</a>" in queue.text
    assert f"/review/cases/{graph['case']['id']}?post=" not in queue.text


def test_start_review_uses_post_redirect_and_get_is_read_only(
    client: TestClient, db_session: Session
) -> None:
    graph = _web_graph(client, "WEB_START")
    case_id = graph["case"]["id"]

    get_page = client.get(f"/review/cases/{case_id}")
    row = db_session.get(ReviewCase, UUID(case_id))
    assert get_page.status_code == 200
    assert row is not None and row.status.value == "QUEUED"

    _start_web_case(client, case_id)
    db_session.expire_all()
    row = db_session.get(ReviewCase, UUID(case_id))
    assert row is not None and row.status.value == "IN_REVIEW"
    assert "Review started" in client.get(f"/review/cases/{case_id}?message=Review+started").text


def test_started_case_shows_only_approve_reject_and_comment(client: TestClient) -> None:
    graph = _web_graph(client, "WEB_SIMPLE_DECISIONS")
    _start_web_case(client, graph["case"]["id"])

    page = client.get(f"/review/cases/{graph['case']['id']}")

    assert 'type="radio"' in page.text
    assert "Reviewer Comment" in page.text
    assert page.text.count('name="comment"') == 1
    assert "Final Approve Advertisement" in page.text
    assert "Final Reject Advertisement" in page.text
    assert "Reviewer identifier" not in page.text
    assert "Correct and Approve" not in page.text
    assert "Request Re-verification" not in page.text


def test_approve_as_is_redirects_and_displays_final_decision(client: TestClient) -> None:
    graph = _web_graph(client, "WEB_APPROVE")
    item = _field_item(graph["case"])
    _start_web_case(client, graph["case"]["id"])

    response = _decision(client, item["id"], "APPROVE_AS_IS")
    page = client.get(response.headers["location"])
    persisted_item = client.get(f"/api/v1/review-items/{item['id']}").json()

    assert response.status_code == 303
    assert "Final decision: APPROVE AS IS" in page.text
    assert "Reviewed against the displayed official evidence." in page.text
    assert "Reviewer" not in page.text
    assert "APPROVED" in page.text
    assert persisted_item["decision"]["reviewer_identifier"] == "local-review-ui"


def test_reject_requires_note_and_rejected_projection_is_not_eligible(
    client: TestClient,
) -> None:
    graph = _web_graph(client, "WEB_REJECT")
    item = _field_item(graph["case"])
    _start_web_case(client, graph["case"]["id"])

    invalid = _decision(client, item["id"], "REJECT", decision_note="   ")
    still_pending = client.get(f"/api/v1/review-items/{item['id']}").json()
    valid = _decision(client, item["id"], "REJECT", decision_note="Source is ambiguous.")
    page = client.get(valid.headers["location"])

    assert invalid.status_code == 303 and "error=" in invalid.headers["location"]
    assert still_pending["status"] == "PENDING"
    assert "REJECTED" in page.text
    assert "This revision is not eligible for Master publication." in page.text


def test_hidden_legacy_decisions_are_rejected_by_web_endpoint(client: TestClient) -> None:
    graph = _web_graph(client, "WEB_HIDDEN_DECISION")
    item = _field_item(graph["case"])
    _start_web_case(client, graph["case"]["id"])

    response = _decision(client, item["id"], "REQUEST_REVERIFICATION")

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    assert "supports+only+Approve+or+Reject" in response.headers["location"]


def test_revision_item_has_no_correction_control(client: TestClient) -> None:
    graph = build_review_graph(client, suffix="WEB_REVISION_ITEM")
    revision_item = next(item for item in graph["case"]["items"] if item["scope"] == "REVISION")
    _start_web_case(client, graph["case"]["id"])

    page = client.get(f"/review/cases/{graph['case']['id']}")
    section = page.text.split(f'id="item-{revision_item["id"]}"', 1)[1].split("</article>", 1)[0]

    assert "Revision-level decision" in section
    assert "Approve" in section
    assert "Reject" in section
    assert "Correct and Approve" not in section
    assert "Request Re-verification" not in section


def test_grouped_post_submission_approves_and_rejects_posts_independently(
    client: TestClient, db_session: Session
) -> None:
    graph = _three_post_review_graph(client)
    case_id = graph["case"]["id"]
    _start_web_case(client, case_id)
    case = client.get(f"/api/v1/review-cases/{case_id}").json()

    police_page = client.get(
        f"/review/cases/{case['id']}", params={"post": "assam_police"}
    )
    relevant_pending = [
        item
        for item in case["items"]
        if item["field_path_snapshot"] is None
        or not item["field_path_snapshot"].startswith("posts.")
        or item["field_path_snapshot"].startswith("posts.assam_police.")
    ]
    assert police_page.text.count('type="radio"') == len(relevant_pending) * 2
    assert police_page.text.count('name="comment"') == 1

    approved = _submit_post(
        client, case, "assam_police", final_action="APPROVE_POST"
    )
    assert approved.status_code == 303
    assert "post=assam_police" in approved.headers["location"]
    after_police = client.get(f"/api/v1/review-cases/{case['id']}").json()
    by_path = {item["field_path_snapshot"]: item for item in after_police["items"]}
    assert by_path["application.end_date"]["status"] == "RESOLVED"
    assert by_path["posts.assam_police.vacancies.total"]["status"] == "RESOLVED"
    assert by_path["posts.assam_commando_battalions.vacancies.total"]["status"] == "PENDING"
    assert by_path["posts.dgcd_cghg.vacancies.total"]["status"] == "PENDING"
    assert after_police["status"] == "IN_REVIEW"
    assert db_session.scalar(select(func.count(ReviewItem.id))) == len(case["items"])
    assert db_session.scalar(select(func.count(ReviewDecision.id))) == 2

    active_queue = client.get("/review")
    resolved_queue = client.get("/review", params={"status": "RESOLVED"})
    police_link = f"/review/cases/{case['id']}?post=assam_police"
    assert police_link not in active_queue.text
    assert police_link in resolved_queue.text

    approved_page = client.get(approved.headers["location"])
    assert "Post review outcome" in approved_page.text
    assert "APPROVED" in approved_page.text
    assert 'type="radio"' not in approved_page.text
    commando_page = client.get(
        f"/review/cases/{case['id']}", params={"post": "assam_commando_battalions"}
    )
    shared = commando_page.text.split("Shared Advertisement review items", 1)[1].split(
        "Grade IV Staff - Assam Commando Battalions", 1
    )[0]
    assert "Final decision: APPROVE AS IS" in shared
    assert 'type="radio"' not in shared

    rejected = _submit_post(
        client,
        after_police,
        "assam_commando_battalions",
        final_action="REJECT_POST",
        reject_post_item=True,
    )
    assert rejected.status_code == 303
    after_commando = client.get(f"/api/v1/review-cases/{case['id']}").json()
    by_path = {item["field_path_snapshot"]: item for item in after_commando["items"]}
    assert by_path["posts.assam_commando_battalions.vacancies.total"]["decision"][
        "decision"
    ] == "REJECT"
    assert by_path["posts.dgcd_cghg.vacancies.total"]["status"] == "PENDING"
    assert after_commando["status"] == "IN_REVIEW"

    finished = _submit_post(
        client, after_commando, "dgcd_cghg", final_action="APPROVE_POST"
    )
    assert finished.status_code == 303
    resolved = client.get(f"/api/v1/review-cases/{case['id']}").json()
    projection = client.get(
        f"/api/v1/review-cases/{case['id']}/approved-projection"
    ).json()
    assert resolved["status"] == "RESOLVED"
    assert resolved["outcome"] == "REJECTED"
    assert projection["approved_post_keys"] == ["assam_police", "dgcd_cghg"]
    assert projection["blocked_post_keys"] == ["assam_commando_battalions"]
    assert projection["master_eligible"] is True


def test_grouped_post_submission_validates_all_items_comment_and_focus(
    client: TestClient,
) -> None:
    graph = _three_post_review_graph(client)
    case_id = graph["case"]["id"]
    _start_web_case(client, case_id)
    case = client.get(f"/api/v1/review-cases/{case_id}").json()
    police_items = [
        item
        for item in case["items"]
        if item["field_path_snapshot"] is None
        or not item["field_path_snapshot"].startswith("posts.")
        or item["field_path_snapshot"].startswith("posts.assam_police.")
    ]

    missing_selection = _submit_post(
        client,
        case,
        "assam_police",
        final_action="APPROVE_POST",
        omit_item_id=police_items[0]["id"],
    )
    missing_comment = _submit_post(
        client,
        case,
        "assam_police",
        final_action="APPROVE_POST",
        comment="   ",
    )

    assert "post=assam_police" in missing_selection.headers["location"]
    assert "error=" in missing_selection.headers["location"]
    assert "post=assam_police" in missing_comment.headers["location"]
    persisted = client.get(f"/api/v1/review-cases/{case['id']}").json()
    assert all(item["status"] == "PENDING" for item in persisted["items"])


def test_grouped_legacy_unsplit_review_submits_once(client: TestClient) -> None:
    graph = _web_graph(client, "WEB_GROUPED_LEGACY")
    case = graph["case"]
    _start_web_case(client, case["id"])

    page = client.get(f"/review/cases/{case['id']}")
    response = _submit_post(client, case, None, final_action="APPROVE_POST")
    resolved_page = client.get(response.headers["location"])

    assert "Final Approve Advertisement" in page.text
    assert response.status_code == 303
    assert "Advertisement approved" in resolved_page.text
    assert "Advertisement review outcome" in resolved_page.text
    assert 'type="radio"' not in resolved_page.text


def test_decision_form_errors_are_clear_and_do_not_resolve_item(client: TestClient) -> None:
    graph = _web_graph(client, "WEB_FORM_ERRORS")
    item = _field_item(graph["case"])
    _start_web_case(client, graph["case"]["id"])

    blank_comment = client.post(
        f"/review/items/{item['id']}/decision",
        data={"decision": "APPROVE_AS_IS", "decision_note": "   "},
        follow_redirects=False,
    )
    unsupported_decision = _decision(
        client,
        item["id"],
        "CORRECT_AND_APPROVE",
    )
    accepted = _decision(client, item["id"], "APPROVE_AS_IS")
    conflicting = _decision(
        client,
        item["id"],
        "REJECT",
        decision_note="A different final decision.",
    )

    assert "error=" in blank_comment.headers["location"]
    assert "error=" in unsupported_decision.headers["location"]
    assert "message=" in accepted.headers["location"]
    assert "error=" in conflicting.headers["location"]
    page = client.get(conflicting.headers["location"])
    assert "already has a different final decision" in page.text


def test_cancel_and_html_errors_are_user_friendly(client: TestClient) -> None:
    graph = _web_graph(client, "WEB_CANCEL")
    cancelled = client.post(
        f"/review/cases/{graph['case']['id']}/cancel", follow_redirects=False
    )
    missing = client.get(f"/review/cases/{uuid4()}")
    invalid_filter = client.get("/review", params={"status": "NOT_A_STATUS"})

    assert cancelled.status_code == 303
    assert "CANCELLED" in client.get(cancelled.headers["location"]).text
    assert missing.status_code == 404 and "Review case not found" in missing.text
    assert invalid_filter.status_code == 400
    assert "Invalid review queue filter" in invalid_filter.text
