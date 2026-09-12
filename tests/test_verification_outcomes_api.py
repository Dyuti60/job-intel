from fastapi.testclient import TestClient

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


def maximum_age_field() -> list[dict]:
    return [
        {
            "field_path": "eligibility.maximum_age",
            "value_type": "INTEGER",
            "value": 38,
        }
    ]


def start_case(client: TestClient) -> tuple[dict, dict, dict, dict]:
    _, document, candidate, revision = create_ready_candidate_revision(
        client, fields=maximum_age_field()
    )
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    verification = create_field_verification(
        client, run["id"], revision["fields"][0]["id"]
    )
    return document, candidate, revision, verification


def other_class_evidence(
    client: TestClient,
    *,
    code: str,
    source_class: str,
    excerpt: str,
) -> dict:
    authority = create_authority(
        client,
        code=code,
        name=f"{code} authority",
        official_website_url=f"https://{code.lower()}.example.gov.in",
    )
    endpoint = create_endpoint(
        client,
        authority["id"],
        name=f"{code} verification source",
        canonical_url=f"https://{code.lower()}.example.gov.in/notices",
        source_class=source_class,
    )
    discovery_run = create_run(client, endpoint["id"])
    document = observe_document(
        client,
        discovery_run["id"],
        document_url=f"https://{code.lower()}.example.gov.in/notice.pdf",
        content_text=f"{code} content",
    )["document"]
    return create_evidence(client, document["id"], excerpt=excerpt)


def test_authoritative_support_wins_but_secondary_conflict_stays_visible(
    client: TestClient,
) -> None:
    document, _, revision, verification = start_case(client)
    authoritative_support = create_evidence(
        client,
        document["id"],
        source_locator="page=4",
        excerpt="Maximum age is 38 years.",
    )
    secondary_conflict = other_class_evidence(
        client,
        code="SECONDARY_A",
        source_class="SECONDARY_DISCOVERY_ONLY",
        excerpt="Maximum age is 35 years.",
    )
    add_verification_assessment(
        client,
        verification["id"],
        authoritative_support["id"],
        "SUPPORTS",
        asserted_value=38,
        asserted_value_type="INTEGER",
    )
    add_verification_assessment(
        client,
        verification["id"],
        secondary_conflict["id"],
        "CONTRADICTS",
        asserted_value=35,
        asserted_value_type="INTEGER",
        assessment_note="Secondary listing differs.",
    )

    confirmed = finalize_field_verification(client, verification["id"])

    assert confirmed["outcome"] == "CONFIRMED"
    assert confirmed["reason_code"] == "AUTHORITATIVE_SUPPORT"
    assert confirmed["authoritative_support_count"] == 1
    assert confirmed["secondary_conflict_count"] == 1
    assert "secondary conflicts=1" in confirmed["finding_summary"]
    secondary_detail = next(
        item
        for item in confirmed["assessments"]
        if item["evidence_id"] == secondary_conflict["id"]
    )
    assert secondary_detail["assessment"] == "CONTRADICTS"
    assert secondary_detail["asserted_value"] == 35
    assert secondary_detail["source_class"] == "SECONDARY_DISCOVERY_ONLY"
    assert secondary_detail["source_document_id"]
    assert secondary_detail["source_endpoint_id"]
    assert secondary_detail["evidence_excerpt"] == "Maximum age is 35 years."

    # Re-verification uses a new run and preserves the earlier confirmed result.
    second_run = create_verification_run(client, revision["id"], "RETRY")
    start_verification_run(client, second_run["id"])
    second_verification = create_field_verification(
        client, second_run["id"], revision["fields"][0]["id"]
    )
    authoritative_conflict = create_evidence(
        client,
        document["id"],
        source_locator="page=5",
        excerpt="A corrigendum states maximum age 35 years.",
    )
    for evidence, assessment, value in [
        (authoritative_support, "SUPPORTS", 38),
        (secondary_conflict, "CONTRADICTS", 35),
        (authoritative_conflict, "CONTRADICTS", 35),
    ]:
        add_verification_assessment(
            client,
            second_verification["id"],
            evidence["id"],
            assessment,
            asserted_value=value,
            asserted_value_type="INTEGER",
        )

    conflicted = finalize_field_verification(client, second_verification["id"])
    old_result = client.get(
        f"/api/v1/field-verifications/{verification['id']}"
    ).json()

    assert conflicted["outcome"] == "CONFLICT"
    assert conflicted["reason_code"] == "AUTHORITATIVE_CONFLICT"
    assert old_result["outcome"] == "CONFIRMED"


def test_supporting_support_and_secondary_contradiction_is_source_conflict(
    client: TestClient,
) -> None:
    _, _, _, verification = start_case(client)
    supporting = other_class_evidence(
        client,
        code="SUPPORTING_B",
        source_class="OFFICIAL_SUPPORTING",
        excerpt="Supporting government page states age 38.",
    )
    secondary = other_class_evidence(
        client,
        code="SECONDARY_B",
        source_class="SECONDARY_DISCOVERY_ONLY",
        excerpt="Secondary page states age 35.",
    )
    add_verification_assessment(
        client,
        verification["id"],
        supporting["id"],
        "SUPPORTS",
        asserted_value=38,
        asserted_value_type="INTEGER",
    )
    add_verification_assessment(
        client,
        verification["id"],
        secondary["id"],
        "CONTRADICTS",
        asserted_value=35,
        asserted_value_type="INTEGER",
    )

    result = finalize_field_verification(client, verification["id"])

    assert result["outcome"] == "CONFLICT"
    assert result["reason_code"] == "SOURCE_CONFLICT"


def test_only_secondary_support_is_insufficient(client: TestClient) -> None:
    _, _, _, verification = start_case(client)
    secondary = other_class_evidence(
        client,
        code="SECONDARY_C",
        source_class="SECONDARY_DISCOVERY_ONLY",
        excerpt="Secondary page states age 38.",
    )
    add_verification_assessment(
        client,
        verification["id"],
        secondary["id"],
        "SUPPORTS",
        asserted_value=38,
        asserted_value_type="INTEGER",
    )

    result = finalize_field_verification(client, verification["id"])

    assert result["outcome"] == "INSUFFICIENT_EVIDENCE"
    assert result["reason_code"] == "ONLY_SECONDARY_EVIDENCE"


def test_no_evidence_and_context_only_are_insufficient(client: TestClient) -> None:
    document, _, revision, no_evidence_verification = start_case(client)
    no_evidence = finalize_field_verification(client, no_evidence_verification["id"])
    assert no_evidence["reason_code"] == "NO_EVIDENCE"

    second_run = create_verification_run(client, revision["id"], "RETRY")
    start_verification_run(client, second_run["id"])
    context_verification = create_field_verification(
        client, second_run["id"], revision["fields"][0]["id"]
    )
    context = create_evidence(client, document["id"], excerpt="Age reference date")
    add_verification_assessment(
        client, context_verification["id"], context["id"], "CONTEXT_ONLY"
    )
    context_result = finalize_field_verification(client, context_verification["id"])

    assert context_result["outcome"] == "INSUFFICIENT_EVIDENCE"
    assert context_result["reason_code"] == "INSUFFICIENT_SUPPORT"


def test_not_applicable_requires_explicit_finalize_input(client: TestClient) -> None:
    _, _, _, verification = start_case(client)

    result = finalize_field_verification(
        client, verification["id"], not_applicable=True
    )
    replay = client.post(
        f"/api/v1/field-verifications/{verification['id']}/finalize",
        json={"not_applicable": True},
    )
    changed_replay = client.post(
        f"/api/v1/field-verifications/{verification['id']}/finalize",
        json={"not_applicable": False},
    )

    assert result["outcome"] == "NOT_APPLICABLE"
    assert result["reason_code"] == "MANUALLY_MARKED_NOT_APPLICABLE"
    assert replay.status_code == 200
    assert changed_replay.status_code == 409


def test_counters_completion_and_input_immutability(client: TestClient) -> None:
    _, document, candidate, revision = create_ready_candidate_revision(client)
    original_revision = client.get(
        f"/api/v1/candidate-revisions/{revision['id']}"
    ).json()
    evidence = create_evidence(client, document["id"], excerpt="Official source context")
    original_evidence = client.get(f"/api/v1/evidence/{evidence['id']}").json()
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    first = create_field_verification(client, run["id"], revision["fields"][0]["id"])
    second = create_field_verification(client, run["id"], revision["fields"][1]["id"])
    add_verification_assessment(
        client,
        first["id"],
        evidence["id"],
        "SUPPORTS",
        asserted_value=revision["fields"][0]["value"],
        asserted_value_type=revision["fields"][0]["value_type"],
    )
    finalize_field_verification(client, first["id"])
    replay = client.post(
        f"/api/v1/field-verifications/{first['id']}/finalize",
        json={"not_applicable": False},
    )
    finalize_field_verification(client, second["id"])

    current_run = client.get(f"/api/v1/verification-runs/{run['id']}").json()
    completed = client.post(
        f"/api/v1/verification-runs/{run['id']}/complete",
        json={"status": "COMPLETED"},
    )

    assert replay.status_code == 200
    assert current_run["fields_confirmed"] == 1
    assert current_run["fields_insufficient"] == 1
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert client.get(f"/api/v1/candidate-revisions/{revision['id']}").json() == (
        original_revision
    )
    assert client.get(f"/api/v1/evidence/{evidence['id']}").json() == original_evidence
    assert client.get(f"/api/v1/recruitment-candidates/{candidate['id']}").json()[
        "status"
    ] == "READY_FOR_VERIFICATION"


def test_partial_completion_and_completed_requires_all_fields(
    client: TestClient,
) -> None:
    _, _, _, revision = create_ready_candidate_revision(client)
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    verification = create_field_verification(
        client, run["id"], revision["fields"][0]["id"]
    )
    finalize_field_verification(client, verification["id"])

    premature = client.post(
        f"/api/v1/verification-runs/{run['id']}/complete",
        json={"status": "COMPLETED"},
    )
    partial = client.post(
        f"/api/v1/verification-runs/{run['id']}/complete",
        json={"status": "PARTIAL", "error_code": "FIELD_PENDING"},
    )
    new_field = client.post(
        f"/api/v1/verification-runs/{run['id']}/fields/{revision['fields'][1]['id']}"
    )

    assert premature.status_code == 409
    assert partial.status_code == 200
    assert partial.json()["error_code"] == "FIELD_PENDING"
    assert new_field.status_code == 409


def test_finalized_field_rejects_new_assessment(client: TestClient) -> None:
    document, _, _, verification = start_case(client)
    finalize_field_verification(client, verification["id"])
    late_evidence = create_evidence(client, document["id"], excerpt="Late evidence")

    response = client.post(
        f"/api/v1/field-verifications/{verification['id']}/evidence",
        json={"evidence_id": late_evidence["id"], "assessment": "CONTEXT_ONLY"},
    )

    assert response.status_code == 409
    assert "immutable" in response.json()["detail"]
