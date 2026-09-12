from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.candidates import CandidateField
from app.models.review import ReviewCase
from app.models.verification import VerificationRun
from tests.factories import create_evidence
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
        "reviewer_identifier": "local-reviewer",
        **values,
    }
    return client.post(
        f"/review/items/{item_id}/decision",
        data=payload,
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


def test_mandatory_deadline_correction_resolves_and_projects_without_mutation(
    client: TestClient, db_session: Session
) -> None:
    graph = _web_graph(client, "WEB_CORRECT")
    review_case = graph["case"]
    item = _field_item(review_case)
    field_id = UUID(graph["revision"]["fields"][0]["id"])
    _start_web_case(client, review_case["id"])

    response = _decision(
        client,
        item["id"],
        "CORRECT_AND_APPROVE",
        decision_note="The authoritative deadline is later.",
        corrected_value="2026-10-27",
    )

    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert "APPROVED WITH CORRECTIONS" in page.text
    assert "Original" in page.text and "2026-10-20" in page.text
    assert "Corrected" in page.text and "2026-10-27" in page.text
    assert "Approved Projection" in page.text
    db_session.expire_all()
    field = db_session.get(CandidateField, field_id)
    assert field is not None and field.value == "2026-10-20"


def test_approve_as_is_redirects_and_displays_final_decision(client: TestClient) -> None:
    graph = _web_graph(client, "WEB_APPROVE")
    item = _field_item(graph["case"])
    _start_web_case(client, graph["case"]["id"])

    response = _decision(client, item["id"], "APPROVE_AS_IS")
    page = client.get(response.headers["location"])

    assert response.status_code == 303
    assert "Final decision: APPROVE AS IS" in page.text
    assert "local-reviewer" in page.text
    assert "APPROVED" in page.text


def test_reject_requires_note_and_rejected_projection_is_not_eligible(
    client: TestClient,
) -> None:
    graph = _web_graph(client, "WEB_REJECT")
    item = _field_item(graph["case"])
    _start_web_case(client, graph["case"]["id"])

    invalid = _decision(client, item["id"], "REJECT")
    still_pending = client.get(f"/api/v1/review-items/{item['id']}").json()
    valid = _decision(client, item["id"], "REJECT", decision_note="Source is ambiguous.")
    page = client.get(valid.headers["location"])

    assert invalid.status_code == 303 and "error=" in invalid.headers["location"]
    assert still_pending["status"] == "PENDING"
    assert "REJECTED" in page.text
    assert "This revision is not eligible for Master publication." in page.text


def test_reverification_requires_note_and_does_not_create_run(
    client: TestClient, db_session: Session
) -> None:
    graph = _web_graph(client, "WEB_REVERIFY")
    item = _field_item(graph["case"])
    _start_web_case(client, graph["case"]["id"])
    before = db_session.scalar(select(func.count(VerificationRun.id)))

    invalid = _decision(client, item["id"], "REQUEST_REVERIFICATION")
    valid = _decision(
        client,
        item["id"],
        "REQUEST_REVERIFICATION",
        decision_note="Re-check the latest official notice.",
    )
    after = db_session.scalar(select(func.count(VerificationRun.id)))
    page = client.get(valid.headers["location"])

    assert invalid.status_code == valid.status_code == 303
    assert before == after
    assert "REVERIFICATION REQUESTED" in page.text
    assert "This revision is not eligible for Master publication." in page.text


def test_revision_item_has_no_correction_control(client: TestClient) -> None:
    graph = build_review_graph(client, suffix="WEB_REVISION_ITEM")
    revision_item = next(item for item in graph["case"]["items"] if item["scope"] == "REVISION")
    _start_web_case(client, graph["case"]["id"])

    page = client.get(f"/review/cases/{graph['case']['id']}")
    section = page.text.split(f'id="item-{revision_item["id"]}"', 1)[1].split("</article>", 1)[0]

    assert "Revision-level decision" in section
    assert "Approve As Is" in section
    assert "Reject" in section
    assert "Request Re-verification" in section
    assert "Correct and Approve" not in section


def test_decision_form_errors_are_clear_and_do_not_resolve_item(client: TestClient) -> None:
    graph = _web_graph(client, "WEB_FORM_ERRORS")
    item = _field_item(graph["case"])
    _start_web_case(client, graph["case"]["id"])

    blank_reviewer = client.post(
        f"/review/items/{item['id']}/decision",
        data={"decision": "APPROVE_AS_IS", "reviewer_identifier": "   "},
        follow_redirects=False,
    )
    invalid_date = _decision(
        client,
        item["id"],
        "CORRECT_AND_APPROVE",
        decision_note="Correcting the date.",
        corrected_value="not-a-date",
    )
    accepted = _decision(client, item["id"], "APPROVE_AS_IS")
    conflicting = _decision(
        client,
        item["id"],
        "REJECT",
        decision_note="A different final decision.",
    )

    assert "error=" in blank_reviewer.headers["location"]
    assert "error=" in invalid_date.headers["location"]
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
