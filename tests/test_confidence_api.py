import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.confidence import get_confidence_policy
from app.models.confidence import FieldConfidenceAssessment
from app.services.confidence_policy import (
    ConfidencePolicyV1,
    classify_field_criticality,
)
from tests.factories import (
    add_verification_assessment,
    create_authority,
    create_endpoint,
    create_evidence,
    create_field_verification,
    create_ready_candidate_revision,
    create_run,
    create_verification_run,
    finalize_field_verification,
    observe_document,
    start_verification_run,
)


def source_evidence(
    client: TestClient,
    *,
    suffix: str,
    source_class: str,
    excerpt: str,
) -> dict:
    authority = create_authority(
        client,
        code=f"CONF_{suffix}",
        name=f"Confidence source {suffix}",
        official_website_url=f"https://{suffix.lower()}.confidence.gov.in",
    )
    endpoint = create_endpoint(
        client,
        authority["id"],
        name=f"Confidence {suffix}",
        canonical_url=f"https://{suffix.lower()}.confidence.gov.in/notices",
        source_class=source_class,
    )
    run = create_run(client, endpoint["id"])
    document = observe_document(
        client,
        run["id"],
        document_url=f"https://{suffix.lower()}.confidence.gov.in/notice.pdf",
        content_text=f"controlled {suffix} content",
    )["document"]
    return create_evidence(client, document["id"], excerpt=excerpt)


def create_single_field_case(
    client: TestClient,
    *,
    field_path: str = "application.end_date",
    value_type: str = "DATE",
    value="2026-10-31",
    suffix: str | None = None,
) -> tuple[dict, dict, dict]:
    fields = [{"field_path": field_path, "value_type": value_type, "value": value}]
    authority_overrides = None
    endpoint_overrides = None
    if suffix is not None:
        authority_overrides = {
            "code": f"CASE_{suffix}",
            "name": f"Case {suffix}",
            "official_website_url": f"https://case-{suffix}.example.gov.in",
        }
        endpoint_overrides = {"canonical_url": f"https://case-{suffix}.example.gov.in/notices"}
    _, document, _, revision = create_ready_candidate_revision(
        client,
        fields=fields,
        authority_overrides=authority_overrides,
        endpoint_overrides=endpoint_overrides,
    )
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    verification = create_field_verification(client, run["id"], revision["fields"][0]["id"])
    return document, run, verification


def complete_run(client: TestClient, run_id: str, status: str = "COMPLETED") -> dict:
    response = client.post(
        f"/api/v1/verification-runs/{run_id}/complete",
        json={"status": status},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_clean_authoritative_confirmation_and_idempotent_api(
    client: TestClient,
) -> None:
    document, run, verification = create_single_field_case(
        client,
        field_path="recruitment_name",
        value_type="STRING",
        value="Assam Recruitment",
    )
    evidence = create_evidence(client, document["id"], excerpt="Assam Recruitment")
    add_verification_assessment(
        client,
        verification["id"],
        evidence["id"],
        "SUPPORTS",
        asserted_value="Assam Recruitment",
        asserted_value_type="STRING",
    )
    finalize_field_verification(client, verification["id"])
    complete_run(client, run["id"])

    first = client.post(f"/api/v1/field-verifications/{verification['id']}/confidence")
    replay = client.post(f"/api/v1/field-verifications/{verification['id']}/confidence")
    retrieved = client.get(f"/api/v1/field-verifications/{verification['id']}/confidence")

    assert first.status_code == 201
    assert replay.status_code == retrieved.status_code == 200
    assert replay.json()["id"] == first.json()["id"] == retrieved.json()["id"]
    assert first.json()["policy_version"] == "V1"
    assert first.json()["score"] == 90
    assert first.json()["criticality"] == "STANDARD"
    assert first.json()["review_required"] is False
    assert first.json()["review_priority"] == "NONE"


def test_critical_authoritative_support_with_secondary_contradiction(
    client: TestClient,
) -> None:
    document, _, verification = create_single_field_case(client)
    official = create_evidence(client, document["id"], excerpt="Last date: 31-10-2026")
    secondary = source_evidence(
        client,
        suffix="SECONDARY_DATE",
        source_class="SECONDARY_DISCOVERY_ONLY",
        excerpt="Last date: 25-10-2026",
    )
    add_verification_assessment(
        client,
        verification["id"],
        official["id"],
        "SUPPORTS",
        asserted_value="2026-10-31",
        asserted_value_type="DATE",
    )
    add_verification_assessment(
        client,
        verification["id"],
        secondary["id"],
        "CONTRADICTS",
        asserted_value="2026-10-25",
        asserted_value_type="DATE",
    )
    result = finalize_field_verification(client, verification["id"])
    confidence = client.post(f"/api/v1/field-verifications/{verification['id']}/confidence").json()

    assert result["outcome"] == "CONFIRMED"
    assert confidence["criticality"] == "CRITICAL"
    assert confidence["score"] == 85
    secondary_component = next(
        item
        for item in confidence["component_breakdown"]["conflicts"]
        if item["component"] == "secondary_conflict_endpoint"
    )
    assert secondary_component["points"] == -5
    assert confidence["component_breakdown"]["base"]["reason"] == ("AUTHORITATIVE_SUPPORT")
    assert "CRITICAL_FIELD_BELOW_THRESHOLD" in confidence["review_reason_codes"]


def test_authoritative_conflict_is_low_and_critical_priority(
    client: TestClient,
) -> None:
    document, _, verification = create_single_field_case(client)
    evidence = create_evidence(client, document["id"], excerpt="Last date: 25-10-2026")
    add_verification_assessment(
        client,
        verification["id"],
        evidence["id"],
        "CONTRADICTS",
        asserted_value="2026-10-25",
        asserted_value_type="DATE",
    )
    finalize_field_verification(client, verification["id"])

    confidence = client.post(f"/api/v1/field-verifications/{verification['id']}/confidence").json()

    assert confidence["score"] <= 25
    assert confidence["review_required"] is True
    assert confidence["review_priority"] == "CRITICAL"
    assert "AUTHORITATIVE_CONFLICT" in confidence["review_reason_codes"]


def test_source_conflict_secondary_only_no_evidence_and_context_only(
    client: TestClient,
) -> None:
    cases = []
    for index in range(4):
        document, _, verification = create_single_field_case(
            client,
            field_path=f"description.case_{index}",
            value_type="STRING",
            value="expected",
            suffix=str(index),
        )
        cases.append((document, verification))

    supporting = source_evidence(
        client,
        suffix="SUPPORT_CONFLICT",
        source_class="OFFICIAL_SUPPORTING",
        excerpt="expected",
    )
    secondary_conflict = source_evidence(
        client,
        suffix="SECONDARY_CONFLICT",
        source_class="SECONDARY_DISCOVERY_ONLY",
        excerpt="different",
    )
    for evidence, assessment, asserted in [
        (supporting, "SUPPORTS", "expected"),
        (secondary_conflict, "CONTRADICTS", "different"),
    ]:
        add_verification_assessment(
            client,
            cases[0][1]["id"],
            evidence["id"],
            assessment,
            asserted_value=asserted,
            asserted_value_type="STRING",
        )

    secondary_support = source_evidence(
        client,
        suffix="SECONDARY_ONLY",
        source_class="SECONDARY_DISCOVERY_ONLY",
        excerpt="expected",
    )
    add_verification_assessment(
        client,
        cases[1][1]["id"],
        secondary_support["id"],
        "SUPPORTS",
        asserted_value="expected",
        asserted_value_type="STRING",
    )
    context = create_evidence(client, cases[3][0]["id"], excerpt="surrounding context")
    add_verification_assessment(client, cases[3][1]["id"], context["id"], "CONTEXT_ONLY")

    expected = [
        ("SOURCE_CONFLICT", 32, "SOURCE_CONFLICT"),
        ("ONLY_SECONDARY_EVIDENCE", 46, "ONLY_SECONDARY_EVIDENCE"),
        ("NO_EVIDENCE", 20, "INSUFFICIENT_EVIDENCE"),
        ("INSUFFICIENT_SUPPORT", 40, "INSUFFICIENT_EVIDENCE"),
    ]
    for (_, verification), (reason, score, review_reason) in zip(cases, expected, strict=True):
        finalized = finalize_field_verification(client, verification["id"])
        confidence = client.post(
            f"/api/v1/field-verifications/{verification['id']}/confidence"
        ).json()
        assert finalized["reason_code"] == reason
        assert confidence["score"] == score
        assert confidence["review_required"] is True
        assert review_reason in confidence["review_reason_codes"]


def test_distinct_endpoint_deduplication_and_deterministic_breakdown(
    client: TestClient,
) -> None:
    document, _, verification = create_single_field_case(
        client,
        field_path="description.summary",
        value_type="STRING",
        value="expected",
    )
    primary = create_evidence(client, document["id"], excerpt="primary expected")
    supporting = source_evidence(
        client,
        suffix="DEDUPE_SUPPORT",
        source_class="OFFICIAL_SUPPORTING",
        excerpt="support one",
    )
    support_document_id = supporting["source_document_id"]
    supporting_two = create_evidence(
        client, support_document_id, excerpt="support two from same endpoint"
    )
    for evidence in [primary, supporting, supporting_two]:
        add_verification_assessment(
            client,
            verification["id"],
            evidence["id"],
            "SUPPORTS",
            asserted_value="expected",
            asserted_value_type="STRING",
        )
    finalize_field_verification(client, verification["id"])
    confidence = client.post(f"/api/v1/field-verifications/{verification['id']}/confidence").json()

    official_component = next(
        item
        for item in confidence["component_breakdown"]["support"]
        if item["component"] == "official_supporting_support_endpoint"
    )
    assert official_component["distinct_endpoint_count"] == 1
    assert official_component["points"] == 2
    assert confidence["score"] == 92


def test_assessment_input_order_does_not_change_score_or_breakdown(
    client: TestClient,
) -> None:
    cases = [
        create_single_field_case(
            client,
            field_path="description.ordering",
            value_type="STRING",
            value="expected",
            suffix=f"ORDER_{index}",
        )
        for index in range(2)
    ]
    supporting = source_evidence(
        client,
        suffix="ORDER_SUPPORTING",
        source_class="OFFICIAL_SUPPORTING",
        excerpt="expected",
    )
    secondary = source_evidence(
        client,
        suffix="ORDER_SECONDARY",
        source_class="SECONDARY_DISCOVERY_ONLY",
        excerpt="different",
    )
    ordered = [(supporting, "SUPPORTS", "expected"), (secondary, "CONTRADICTS", "different")]
    results = []
    for index, (_, _, verification) in enumerate(cases):
        for evidence, assessment, value in ordered if index == 0 else reversed(ordered):
            add_verification_assessment(
                client,
                verification["id"],
                evidence["id"],
                assessment,
                asserted_value=value,
                asserted_value_type="STRING",
            )
        finalize_field_verification(client, verification["id"])
        results.append(
            client.post(f"/api/v1/field-verifications/{verification['id']}/confidence").json()
        )

    assert results[0]["score"] == results[1]["score"] == 32
    assert results[0]["component_breakdown"] == results[1]["component_breakdown"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("application.end_date", "CRITICAL"),
        ("eligibility.maximum_age", "CRITICAL"),
        ("qualification.summary", "CRITICAL"),
        ("vacancies.total", "CRITICAL"),
        ("posts.0.eligibility.education", "CRITICAL"),
        ("recruitment_name", "STANDARD"),
        ("future.unknown", "STANDARD"),
    ],
)
def test_v1_criticality_rules(path: str, expected: str) -> None:
    assert classify_field_criticality(path).value == expected


def test_critical_secondary_support_cannot_bypass_review(
    client: TestClient,
) -> None:
    _, _, verification = create_single_field_case(client)
    for suffix in ["SECONDARY_ONE", "SECONDARY_TWO"]:
        evidence = source_evidence(
            client,
            suffix=suffix,
            source_class="SECONDARY_DISCOVERY_ONLY",
            excerpt="Last date 31-10-2026",
        )
        add_verification_assessment(
            client,
            verification["id"],
            evidence["id"],
            "SUPPORTS",
            asserted_value="2026-10-31",
            asserted_value_type="DATE",
        )
    finalize_field_verification(client, verification["id"])
    confidence = client.post(f"/api/v1/field-verifications/{verification['id']}/confidence").json()

    assert confidence["score"] == 47
    assert confidence["review_required"] is True
    assert "CRITICAL_FIELD_NO_AUTHORITATIVE_SUPPORT" in confidence["review_reason_codes"]
    assert confidence["review_priority"] == "HIGH"


def test_threshold_override_changes_routing_not_score(client: TestClient) -> None:
    document, _, verification = create_single_field_case(
        client,
        field_path="recruitment_name",
        value_type="STRING",
        value="Expected",
    )
    evidence = create_evidence(client, document["id"], excerpt="Expected")
    add_verification_assessment(
        client,
        verification["id"],
        evidence["id"],
        "SUPPORTS",
        asserted_value="Expected",
        asserted_value_type="STRING",
    )
    finalize_field_verification(client, verification["id"])
    client.app.dependency_overrides[get_confidence_policy] = lambda: ConfidencePolicyV1(
        standard_threshold=95,
        critical_threshold=95,
        revision_threshold=95,
    )
    try:
        response = client.post(f"/api/v1/field-verifications/{verification['id']}/confidence")
    finally:
        client.app.dependency_overrides.pop(get_confidence_policy, None)

    assert response.status_code == 201
    assert response.json()["score"] == 90
    assert response.json()["review_required"] is True
    assert "FIELD_SCORE_BELOW_THRESHOLD" in response.json()["review_reason_codes"]


def test_revision_weighting_not_applicable_and_idempotency(client: TestClient) -> None:
    fields = [
        {"field_path": "application.end_date", "value_type": "DATE", "value": "2026-10-31"},
        {"field_path": "description.summary", "value_type": "STRING", "value": "Summary"},
        {"field_path": "description.optional", "value_type": "NULL", "value": None},
    ]
    _, document, _, revision = create_ready_candidate_revision(client, fields=fields)
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    evidence = create_evidence(client, document["id"], excerpt="Official values")
    for field in revision["fields"]:
        verification = create_field_verification(client, run["id"], field["id"])
        if field["field_path"] == "description.optional":
            finalize_field_verification(client, verification["id"], not_applicable=True)
            continue
        add_verification_assessment(
            client,
            verification["id"],
            evidence["id"],
            "SUPPORTS",
            asserted_value=field["value"],
            asserted_value_type=field["value_type"],
        )
        finalize_field_verification(client, verification["id"])
    complete_run(client, run["id"])

    first = client.post(f"/api/v1/verification-runs/{run['id']}/confidence")
    replay = client.post(f"/api/v1/verification-runs/{run['id']}/confidence")
    retrieved = client.get(f"/api/v1/verification-runs/{run['id']}/confidence")

    assert first.status_code == 201
    assert replay.status_code == retrieved.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert first.json()["score"] == 90
    assert first.json()["coverage_ratio"] == "1.0000"
    assert first.json()["fields_scored"] == 2
    assert first.json()["fields_not_applicable"] == 1
    assert first.json()["critical_fields_total"] == 1
    assert first.json()["review_required"] is False


def test_partial_run_coverage_requires_review(client: TestClient) -> None:
    _, document, _, revision = create_ready_candidate_revision(client)
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    field = revision["fields"][0]
    verification = create_field_verification(client, run["id"], field["id"])
    evidence = create_evidence(client, document["id"], excerpt="Official value")
    add_verification_assessment(
        client,
        verification["id"],
        evidence["id"],
        "SUPPORTS",
        asserted_value=field["value"],
        asserted_value_type=field["value_type"],
    )
    finalize_field_verification(client, verification["id"])
    complete_run(client, run["id"], "PARTIAL")

    result = client.post(f"/api/v1/verification-runs/{run['id']}/confidence")

    assert result.status_code == 201
    assert result.json()["coverage_ratio"] == "0.5000"
    assert result.json()["score"] == 45
    assert result.json()["review_required"] is True
    assert "PARTIAL_VERIFICATION" in result.json()["review_reason_codes"]
    assert "REVISION_SCORE_BELOW_THRESHOLD" in result.json()["review_reason_codes"]


def test_low_critical_field_cannot_be_masked_by_nine_high_fields(
    client: TestClient,
) -> None:
    fields = [
        {"field_path": "application.end_date", "value_type": "DATE", "value": "2026-10-31"}
    ] + [
        {
            "field_path": f"description.item_{index}",
            "value_type": "STRING",
            "value": f"value {index}",
        }
        for index in range(9)
    ]
    _, document, _, revision = create_ready_candidate_revision(client, fields=fields)
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    evidence = create_evidence(client, document["id"], excerpt="Official field values")
    bonus_evidence = [
        source_evidence(
            client,
            suffix=f"MASK_AUTH_{index}",
            source_class="AUTHORITATIVE_OFFICIAL",
            excerpt=f"Authoritative support {index}",
        )
        for index in range(2)
    ] + [
        source_evidence(
            client,
            suffix=f"MASK_SUPPORT_{index}",
            source_class="OFFICIAL_SUPPORTING",
            excerpt=f"Official supporting evidence {index}",
        )
        for index in range(2)
    ]
    for field in revision["fields"]:
        verification = create_field_verification(client, run["id"], field["id"])
        if field["field_path"] != "application.end_date":
            for support in [evidence, *bonus_evidence]:
                add_verification_assessment(
                    client,
                    verification["id"],
                    support["id"],
                    "SUPPORTS",
                    asserted_value=field["value"],
                    asserted_value_type=field["value_type"],
                )
        finalize_field_verification(client, verification["id"])
    complete_run(client, run["id"])

    result = client.post(f"/api/v1/verification-runs/{run['id']}/confidence").json()

    scores = [
        item["score"] for item in result["field_assessments"] if item["criticality"] == "STANDARD"
    ]
    assert scores == [100] * 9
    assert result["score"] > 80
    assert result["critical_fields_requiring_review"] == 1
    assert result["review_required"] is True
    assert result["review_priority"] == "HIGH"


def test_scoring_prerequisites_and_database_score_constraint(
    client: TestClient, db_session: Session
) -> None:
    _, _, verification = create_single_field_case(client)
    pending = client.post(f"/api/v1/field-verifications/{verification['id']}/confidence")
    unknown = client.get(f"/api/v1/field-verifications/{uuid.uuid4()}/confidence")

    assert pending.status_code == 409
    assert unknown.status_code == 404

    finalize_field_verification(client, verification["id"])
    db_session.add(
        FieldConfidenceAssessment(
            field_verification_id=uuid.UUID(verification["id"]),
            policy_version="V1",
            input_hash="a" * 64,
            score=101,
            criticality="CRITICAL",
            review_required=True,
            review_priority="HIGH",
            review_reason_codes=["FIELD_SCORE_BELOW_THRESHOLD"],
            component_breakdown={},
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_confidence_calculation_does_not_mutate_input_domains(
    client: TestClient,
) -> None:
    document, run, verification = create_single_field_case(
        client,
        field_path="recruitment_name",
        value_type="STRING",
        value="Immutable proposal",
    )
    evidence = create_evidence(client, document["id"], excerpt="Immutable proposal")
    add_verification_assessment(
        client,
        verification["id"],
        evidence["id"],
        "SUPPORTS",
        asserted_value="Immutable proposal",
        asserted_value_type="STRING",
    )
    finalized = finalize_field_verification(client, verification["id"])
    completed = complete_run(client, run["id"])
    evidence_before = client.get(f"/api/v1/evidence/{evidence['id']}").json()
    field_before = client.get(
        f"/api/v1/candidate-revisions/{completed['candidate_revision_id']}"
    ).json()

    response = client.post(f"/api/v1/verification-runs/{run['id']}/confidence")

    assert response.status_code == 201
    assert client.get(f"/api/v1/evidence/{evidence['id']}").json() == evidence_before
    assert (
        client.get(f"/api/v1/candidate-revisions/{completed['candidate_revision_id']}").json()
        == field_before
    )
    assert client.get(f"/api/v1/field-verifications/{verification['id']}").json() == finalized
    run_after = client.get(f"/api/v1/verification-runs/{run['id']}").json()
    assert {key: value for key, value in run_after.items() if key != "completed_at"} == {
        key: value for key, value in completed.items() if key != "completed_at"
    }
    assert run_after["completed_at"].rstrip("Z") == completed["completed_at"].rstrip("Z")
