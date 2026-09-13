import uuid

from tests.factories import create_revision, create_run, observe_document
from tests.test_master_api import _publish, _verify_revision
from tests.test_post_master import _explicit_two_post_run


def _publish_valid_sibling(client) -> dict:
    run = _explicit_two_post_run(client)
    confidence = client.post(f"/api/v1/verification-runs/{run['id']}/confidence-v2").json()
    client.post(f"/api/v1/revision-confidence/{confidence['id']}/review-routing")
    case = client.post(
        "/api/v1/review-cases",
        json={"revision_confidence_assessment_id": confidence["id"]},
    ).json()
    client.post(f"/api/v1/review-cases/{case['id']}/start")
    client.post(
        f"/api/v1/review-items/{case['items'][0]['id']}/decision",
        json={
            "decision": "REJECT",
            "reviewer_identifier": "post-reviewer",
            "decision_note": "Exclude the conflicted Post.",
        },
    )
    response = client.post(
        "/api/v1/recruitment-master/publish",
        json={"revision_confidence_assessment_id": confidence["id"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _publish_updated_valid_post(client, first_publication: dict) -> dict:
    first_revision = client.get(
        f"/api/v1/candidate-revisions/"
        f"{first_publication['master_revision']['source_candidate_revision_id']}"
    ).json()
    first_document = client.get(
        f"/api/v1/source-documents/{first_revision['source_document_id']}"
    ).json()
    discovery = create_run(client, first_document["source_endpoint_id"])
    document = observe_document(
        client,
        discovery["id"],
        document_url="https://example.gov.in/updated-two-posts.pdf",
        content_text="updated valid post vacancies",
    )["document"]
    revision = create_revision(
        client,
        first_revision["recruitment_candidate_id"],
        document["id"],
        split_status="EXPLICIT",
        fields=[
            {
                "field_path": "recruitment_name",
                "value_type": "STRING",
                "value": "Two Post Recruitment",
            }
        ],
        posts=[
            {
                "post_key": "valid_post",
                "ordinal": 1,
                "name": "Valid Post",
                "facts": [
                    {"field_path": "name", "value_type": "STRING", "value": "Valid Post"},
                    {"field_path": "vacancies.total", "value_type": "INTEGER", "value": 11},
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
            }
        ],
    )
    verified = _verify_revision(client, document, revision)
    response = _publish(client, verified["confidence"]["id"])
    assert response.status_code == 201, response.text
    return response.json()


def test_public_contract_uses_approved_post_as_result_unit(client) -> None:
    publication = _publish_valid_sibling(client)
    master_revision = publication["master_revision"]
    public_id = master_revision["posts"][0]["public_id"]
    expected_public_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"assam-job-intelligence:master-post:{publication['master']['id']}:valid_post",
    )
    assert public_id == str(expected_public_id)

    listed = client.get("/api/public/v1/recruitments", params={"q": "Valid Post"})
    detail = client.get(f"/api/public/v1/recruitments/{public_id}")
    legacy_parent = client.get(f"/api/public/v1/recruitments/{publication['master']['id']}")

    assert listed.status_code == detail.status_code == 200
    assert legacy_parent.status_code == 404
    assert listed.json()["total"] == 1
    summary = listed.json()["items"][0]
    assert summary["id"] == public_id
    assert summary["display_name"] == "Valid Post"
    assert summary["advertisement_title"] == "Two Post Recruitment"
    assert summary["post_key"] == "valid_post"
    assert summary["vacancies_total"] == 10
    assert {field["field_path"] for field in detail.json()["fields"]} == {
        "age.maximum",
        "age.minimum",
        "age.reference_date",
        "domicile.requirement",
        "experience.minimum_months",
        "name",
        "qualification.minimum",
        "recruitment_name",
        "vacancies.total",
    }
    assert all("conflicted_post" not in str(field) for field in detail.json()["fields"])
    assert (
        client.get(
            "/api/public/v1/recruitments",
            params={"post_name": "valid", "qualification": "bachelor"},
        ).json()["total"]
        == 1
    )
    assert (
        client.get("/api/public/v1/recruitments", params={"qualification": "doctorate"}).json()[
            "total"
        ]
        == 0
    )

    updated = _publish_updated_valid_post(client, publication)
    assert updated["master_revision"]["revision_number"] == 2
    assert updated["master_revision"]["posts"][0]["public_id"] == public_id
    refreshed = client.get(f"/api/public/v1/recruitments/{public_id}").json()
    assert refreshed["current_revision_number"] == 2
    assert refreshed["vacancies_total"] == 11


def test_eligibility_is_versioned_explainable_and_conservative(client) -> None:
    publication = _publish_valid_sibling(client)
    public_id = publication["master_revision"]["posts"][0]["public_id"]
    endpoint = f"/api/public/v1/recruitments/{public_id}/eligibility"

    eligible = client.post(
        endpoint,
        json={
            "date_of_birth": "2000-01-02",
            "category": "GENERAL",
            "assam_domicile": True,
            "qualifications": ["Bachelor Degree"],
            "experience_months": 24,
        },
    )
    underage = client.post(
        endpoint,
        json={
            "date_of_birth": "2010-01-02",
            "category": "GENERAL",
            "assam_domicile": True,
            "qualifications": ["Bachelor Degree"],
            "experience_months": 24,
        },
    )
    uncertain = client.post(endpoint, json={})
    needs_review = client.post(
        endpoint,
        json={
            "date_of_birth": "1980-01-01",
            "category": "OBC_MOBC",
            "assam_domicile": True,
            "qualifications": ["Bachelor Degree"],
            "experience_months": 24,
        },
    )
    invalid = client.post(endpoint, json={"category": "UNSUPPORTED"})
    missing = client.post(
        "/api/public/v1/recruitments/00000000-0000-0000-0000-000000000000/eligibility",
        json={},
    )

    assert eligible.status_code == underage.status_code == uncertain.status_code == 200
    assert eligible.json()["rule_version"] == "V1"
    assert eligible.json()["overall_outcome"] == "ELIGIBLE"
    assert {item["outcome"] for item in eligible.json()["criteria"]} == {"ELIGIBLE"}
    assert underage.json()["overall_outcome"] == "NOT_ELIGIBLE"
    assert (
        next(item for item in underage.json()["criteria"] if item["criterion"] == "AGE")["outcome"]
        == "NOT_ELIGIBLE"
    )
    assert uncertain.json()["overall_outcome"] == "UNKNOWN"
    assert all(item["outcome"] == "UNKNOWN" for item in uncertain.json()["criteria"])
    assert needs_review.json()["overall_outcome"] == "REVIEW_REQUIRED"
    assert (
        "no structured relaxation"
        in next(item for item in needs_review.json()["criteria"] if item["criterion"] == "AGE")[
            "explanation"
        ]
    )
    assert invalid.status_code == 422
    assert missing.status_code == 404

    page = client.get(f"/jobs/{public_id}")
    rendered = client.post(
        f"/jobs/{public_id}/eligibility",
        data={
            "date_of_birth": "2000-01-02",
            "category": "GENERAL",
            "assam_domicile": "yes",
            "qualifications": "Bachelor Degree",
            "experience_months": "24",
        },
    )
    assert page.status_code == rendered.status_code == 200
    assert "Advertisement: Two Post Recruitment" in page.text
    assert "Evaluate eligibility" in page.text
    assert "Overall: Eligible" in rendered.text
