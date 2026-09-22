from fastapi.testclient import TestClient

from tests.factories import (
    add_verification_assessment,
    create_candidate,
    create_discovery_source,
    create_evidence,
    create_field_verification,
    create_ready_candidate_revision,
    create_revision,
    create_run,
    create_verification_run,
    finalize_field_verification,
    observe_document,
    start_verification_run,
)


def _completed_case(
    client: TestClient,
    *,
    field_path: str,
    value_type: str,
    value,
    assessment: str = "SUPPORTS",
) -> tuple[dict, dict]:
    fields = [
        {
            "field_path": field_path,
            "value_type": value_type,
            "value": value,
            "source_locator": "pdf:page=2;table=vacancies;row=1",
        }
    ]
    _, document, _, revision = create_ready_candidate_revision(client, fields=fields)
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    verification = create_field_verification(client, run["id"], revision["fields"][0]["id"])
    evidence = create_evidence(client, document["id"], excerpt=str(value))
    add_verification_assessment(
        client,
        verification["id"],
        evidence["id"],
        assessment,
        asserted_value=(value + 1 if assessment == "CONTRADICTS" else value),
        asserted_value_type=value_type,
    )
    finalize_field_verification(client, verification["id"])
    completed = client.post(
        f"/api/v1/verification-runs/{run['id']}/complete", json={"status": "COMPLETED"}
    )
    assert completed.status_code == 200, completed.text
    return run, verification


def test_v2_confidence_is_explainable_neutral_and_idempotent(client: TestClient) -> None:
    run, _ = _completed_case(
        client,
        field_path="posts.grade_iv_assam_police.vacancies.total",
        value_type="INTEGER",
        value=181,
    )

    first = client.post(f"/api/v1/verification-runs/{run['id']}/confidence-v2")
    replay = client.post(f"/api/v1/verification-runs/{run['id']}/confidence-v2")
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    result = first.json()
    assert result["policy_version"] == "V2"
    assert result["score"] == 95
    assert result["review_required"] is False
    assert result["review_reason_codes"] == []
    field = result["field_assessments"][0]
    assert field["criticality"] == "CRITICAL"
    assert field["component_breakdown"]["components"] == {
        "verification_outcome": 50,
        "authoritative_source_quality": 30,
        "official_source_quality": 0,
        "secondary_source_quality": 0,
        "extraction_reliability": 10,
        "source_locator_completeness": 5,
        "supporting_evidence": 0,
        "conflicts": 0,
        "ambiguity": 0,
    }
    assert field["component_breakdown"]["extraction_reliability_tier"] == "DETERMINISTIC"
    assert result["component_breakdown"]["aggregation"]["optional_absence_penalty"] == 0


def test_review_routing_routes_missing_public_required_fields_without_changing_confidence(
    client: TestClient,
) -> None:
    run, _ = _completed_case(
        client,
        field_path="recruitment_name",
        value_type="STRING",
        value="Assam Police Grade IV",
    )
    confidence = client.post(f"/api/v1/verification-runs/{run['id']}/confidence-v2").json()

    first = client.post(f"/api/v1/revision-confidence/{confidence['id']}/review-routing")
    replay = client.post(f"/api/v1/revision-confidence/{confidence['id']}/review-routing")
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    routing = first.json()
    assert routing["review_required"] is True
    assert routing["priority"] == "NORMAL"
    assert routing["reason_codes"] == ["MISSING_PUBLIC_REQUIRED_FIELDS"]
    assert routing["field_routes"] == []
    assert routing["component_breakdown"]["missing_public_required_fields"] == {
        "ADVERTISEMENT": [
            "Post vacancies",
            "Opening date",
            "Closing date",
            "Qualification",
            "Age criteria",
        ]
    }
    assert routing["component_breakdown"]["policy"]["numeric_score_threshold_used"] is False
    assert routing["component_breakdown"]["policy"]["optional_field_absence_routes"] is False
    assert routing["component_breakdown"]["policy"]["publication_decision"] is False
    publish = client.post(
        "/api/v1/recruitment-master/publish",
        json={"revision_confidence_assessment_id": confidence["id"]},
    )
    assert publish.status_code == 409


def test_authoritative_conflict_routes_independently_of_v2_score(client: TestClient) -> None:
    run, _ = _completed_case(
        client,
        field_path="posts.grade_iv_assam_police.vacancies.total",
        value_type="INTEGER",
        value=181,
        assessment="CONTRADICTS",
    )
    confidence = client.post(f"/api/v1/verification-runs/{run['id']}/confidence-v2").json()
    assert confidence["review_required"] is False

    routing = client.post(f"/api/v1/revision-confidence/{confidence['id']}/review-routing").json()
    assert routing["review_required"] is True
    assert routing["priority"] == "CRITICAL"
    assert "AUTHORITATIVE_CONFLICT" in routing["reason_codes"]
    assert routing["field_routes"][0]["field_path"].endswith("vacancies.total")


def test_ambiguous_post_split_routes_without_fabricating_posts(client: TestClient) -> None:
    authority, endpoint = create_discovery_source(client)
    discovery_run = create_run(client, endpoint["id"])
    document = observe_document(client, discovery_run["id"])["document"]
    candidate = create_candidate(client, authority["id"])
    revision = create_revision(
        client,
        candidate["id"],
        document["id"],
        fields=[
            {
                "field_path": "recruitment_name",
                "value_type": "STRING",
                "value": "Grade IV recruitment",
                "source_locator": "pdf:page=1",
            }
        ],
        split_status="AMBIGUOUS",
        split_note="Vacancy table row has a damaged category column.",
    )
    ready = client.patch(
        f"/api/v1/recruitment-candidates/{candidate['id']}",
        json={"status": "READY_FOR_VERIFICATION"},
    )
    assert ready.status_code == 200
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    verification = create_field_verification(client, run["id"], revision["fields"][0]["id"])
    evidence = create_evidence(client, document["id"], excerpt="Grade IV recruitment")
    add_verification_assessment(
        client,
        verification["id"],
        evidence["id"],
        "SUPPORTS",
        asserted_value="Grade IV recruitment",
        asserted_value_type="STRING",
    )
    finalize_field_verification(client, verification["id"])
    completed = client.post(
        f"/api/v1/verification-runs/{run['id']}/complete", json={"status": "COMPLETED"}
    )
    assert completed.status_code == 200

    confidence = client.post(f"/api/v1/verification-runs/{run['id']}/confidence-v2").json()
    assert confidence["component_breakdown"]["advertisement"] == {
        "split_status": "AMBIGUOUS",
        "post_count": 0,
        "ambiguous_split_penalty": 20,
    }
    routing = client.post(f"/api/v1/revision-confidence/{confidence['id']}/review-routing").json()
    assert routing["review_required"] is True
    assert routing["priority"] == "HIGH"
    assert routing["field_routes"] == []
    assert routing["reason_codes"] == [
        "AMBIGUOUS_POST_SPLIT",
        "UNCERTAIN_VACANCY_MAPPING",
        "MISSING_PUBLIC_REQUIRED_FIELDS",
    ]
