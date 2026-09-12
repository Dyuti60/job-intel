"""Run the controlled T-010 corrected-value publication scenario."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.factories import decide_review_item, start_review_case
from tests.test_review_api import build_review_graph


def main() -> None:
    with TestClient(create_app()) as client:
        graph = build_review_graph(
            client,
            suffix="T010_SMOKE",
            modes={"application.end_date": "auth_support_secondary_conflict"},
        )
        review_case = graph["case"]
        assert review_case is not None
        start_review_case(client, review_case["id"])
        field_item = next(item for item in review_case["items"] if item["scope"] == "FIELD")
        decision = decide_review_item(
            client,
            field_item["id"],
            "CORRECT_AND_APPROVE",
            corrected_value_type="DATE",
            corrected_value="2026-10-27",
            decision_note="Controlled T-010 correction smoke test.",
        )
        publish = client.post(
            "/api/v1/recruitment-master/publish",
            json={"revision_confidence_assessment_id": graph["confidence"]["id"]},
        )
        publish.raise_for_status()
        result = publish.json()
        master_revision = client.get(
            f"/api/v1/recruitment-master-revisions/{result['master_revision']['id']}"
        )
        master_revision.raise_for_status()
        master_field = master_revision.json()["fields"][0]
        candidate_revision = client.get(
            f"/api/v1/candidate-revisions/{graph['revision']['id']}"
        )
        candidate_revision.raise_for_status()
        original_field = candidate_revision.json()["fields"][0]

        assert original_field["value"] == "2026-10-20"
        assert master_field["value"] == "2026-10-27"
        assert master_field["value_origin"] == "HUMAN_CORRECTED"
        assert master_field["source_candidate_field_id"] == original_field["id"]
        assert master_field["review_decision_id"] == decision["id"]
        assert result["master_revision"]["publication_path"] == "HUMAN_CORRECTED"
        print(
            "T-010 PostgreSQL smoke passed: original=2026-10-20, "
            "reviewed/master=2026-10-27, traceability preserved."
        )


if __name__ == "__main__":
    main()
