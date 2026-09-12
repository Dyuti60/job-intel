import copy
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.review import ReviewCase, ReviewDecision, ReviewItem
from tests.factories import decide_review_item, start_review_case
from tests.test_review_api import build_review_graph


def test_database_prevents_duplicate_case_for_confidence(
    client: TestClient, db_session: Session
) -> None:
    created = build_review_graph(client, suffix="DB_CASE")["case"]
    assert created is not None
    persisted = db_session.get(ReviewCase, UUID(created["id"]))
    assert persisted is not None
    db_session.add(
        ReviewCase(
            id=uuid4(),
            candidate_revision_id=persisted.candidate_revision_id,
            verification_run_id=persisted.verification_run_id,
            revision_confidence_assessment_id=(persisted.revision_confidence_assessment_id),
            status=persisted.status,
            priority=persisted.priority,
            policy_version=persisted.policy_version,
            revision_score_snapshot=persisted.revision_score_snapshot,
            revision_review_reason_codes_snapshot=copy.deepcopy(
                persisted.revision_review_reason_codes_snapshot
            ),
            component_breakdown_snapshot=copy.deepcopy(persisted.component_breakdown_snapshot),
            opened_at=persisted.opened_at,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_database_prevents_duplicate_item_key_within_case(
    client: TestClient, db_session: Session
) -> None:
    created = build_review_graph(client, suffix="DB_ITEM")["case"]
    assert created is not None
    persisted = db_session.get(ReviewItem, UUID(created["items"][0]["id"]))
    assert persisted is not None
    db_session.add(
        ReviewItem(
            id=uuid4(),
            review_case_id=persisted.review_case_id,
            item_key=persisted.item_key,
            scope=persisted.scope,
            field_confidence_assessment_id=(persisted.field_confidence_assessment_id),
            candidate_field_id=persisted.candidate_field_id,
            status=persisted.status,
            priority=persisted.priority,
            policy_version=persisted.policy_version,
            field_path_snapshot=persisted.field_path_snapshot,
            candidate_value_type_snapshot=persisted.candidate_value_type_snapshot,
            candidate_value_snapshot=copy.deepcopy(persisted.candidate_value_snapshot),
            confidence_score_snapshot=persisted.confidence_score_snapshot,
            review_reason_codes_snapshot=copy.deepcopy(persisted.review_reason_codes_snapshot),
            component_breakdown_snapshot=copy.deepcopy(persisted.component_breakdown_snapshot),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_database_allows_only_one_final_decision_per_item(
    client: TestClient, db_session: Session
) -> None:
    created = build_review_graph(client, suffix="DB_DECISION")["case"]
    assert created is not None
    start_review_case(client, created["id"])
    decision = decide_review_item(client, created["items"][0]["id"], "APPROVE_AS_IS")
    persisted = db_session.get(ReviewDecision, UUID(decision["id"]))
    assert persisted is not None
    db_session.add(
        ReviewDecision(
            id=uuid4(),
            review_item_id=persisted.review_item_id,
            decision=persisted.decision,
            reviewer_identifier="other-reviewer",
            original_value_snapshot=copy.deepcopy(persisted.original_value_snapshot),
            original_value_type_snapshot=persisted.original_value_type_snapshot,
            decided_at=persisted.decided_at,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_database_requires_note_for_reject_decision(
    client: TestClient, db_session: Session
) -> None:
    created = build_review_graph(client, suffix="DB_NOTE")["case"]
    assert created is not None
    start_review_case(client, created["id"])
    item = created["items"][0]
    db_session.add(
        ReviewDecision(
            review_item_id=UUID(item["id"]),
            decision="REJECT",
            reviewer_identifier="reviewer",
            original_value_snapshot=item["candidate_value_snapshot"],
            original_value_type_snapshot=item["candidate_value_type_snapshot"],
            decided_at=copy.copy(db_session.get(ReviewItem, UUID(item["id"])).created_at),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
