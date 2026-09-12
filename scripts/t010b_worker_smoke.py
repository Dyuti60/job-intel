"""Seed and inspect the controlled PostgreSQL T-010B worker scenario."""

import argparse

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.main import create_app
from app.models.master import (
    MasterChange,
    MasterField,
    MasterPublicationEvent,
    RecruitmentMaster,
    RecruitmentMasterRevision,
)
from tests.factories import decide_review_item, start_review_case
from tests.test_master_api import _direct_graph
from tests.test_review_api import build_review_graph


def seed() -> None:
    with TestClient(create_app()) as client:
        direct = _direct_graph(client, "T010B_SMOKE_DIRECT")
        corrected = build_review_graph(client, suffix="T010B_SMOKE_CORRECTED")
        review_case = corrected["case"]
        assert review_case is not None
        start_review_case(client, review_case["id"])
        for item in review_case["items"]:
            if item["scope"] == "FIELD":
                decide_review_item(
                    client,
                    item["id"],
                    "CORRECT_AND_APPROVE",
                    corrected_value_type="DATE",
                    corrected_value="2026-10-27",
                    decision_note="T-010B worker smoke correction.",
                )
            else:
                decide_review_item(client, item["id"], "APPROVE_AS_IS")
        pending = build_review_graph(client, suffix="T010B_SMOKE_PENDING")
        print(
            "Seeded T-010B PostgreSQL scenarios: "
            f"direct={direct['confidence']['id']}, "
            f"corrected={corrected['confidence']['id']}, "
            f"pending={pending['confidence']['id']}."
        )


def inspect() -> None:
    with SessionLocal() as session:
        counts = {
            "masters": session.scalar(select(func.count()).select_from(RecruitmentMaster)),
            "revisions": session.scalar(
                select(func.count()).select_from(RecruitmentMasterRevision)
            ),
            "fields": session.scalar(select(func.count()).select_from(MasterField)),
            "changes": session.scalar(select(func.count()).select_from(MasterChange)),
            "events": session.scalar(select(func.count()).select_from(MasterPublicationEvent)),
        }
        corrected = session.scalar(
            select(MasterField).where(MasterField.value_origin == "HUMAN_CORRECTED")
        )
        assert corrected is not None
        assert corrected.value == "2026-10-27"
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/recruitment-master")
        response.raise_for_status()
        masters = response.json()
    assert len(masters) == 2
    print(
        f"Master API returned {len(masters)} records; counts={counts}; "
        "corrected master value=2026-10-27; pending review remained unpublished."
    )


def seed_dry_run() -> None:
    with TestClient(create_app()) as client:
        direct = _direct_graph(client, "T010B_SMOKE_DRY_RUN")
        print(
            "Seeded dry-run-only direct assessment: "
            f"{direct['confidence']['id']}."
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "seed-dry-run", "inspect"))
    args = parser.parse_args()
    if args.action == "seed":
        seed()
    elif args.action == "seed-dry-run":
        seed_dry_run()
    else:
        inspect()


if __name__ == "__main__":
    main()
