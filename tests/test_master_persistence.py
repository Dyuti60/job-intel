from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.master import (
    MasterChange,
    MasterField,
    MasterPublicationEvent,
    RecruitmentMaster,
    RecruitmentMasterRevision,
)
from tests.test_master_api import _direct_graph, _publish


def _published_objects(client: TestClient, db_session: Session):
    graph = _direct_graph(client, "DB_CONSTRAINTS")
    _publish(client, graph["confidence"]["id"])
    master = db_session.scalar(select(RecruitmentMaster))
    revision = db_session.scalar(select(RecruitmentMasterRevision))
    field = db_session.scalar(select(MasterField))
    event = db_session.scalar(select(MasterPublicationEvent))
    change = db_session.scalar(select(MasterChange))
    assert master and revision and field and event and change
    return master, revision, field, event, change


def test_master_identity_and_revision_identity_are_database_protected(
    client: TestClient, db_session: Session
) -> None:
    master, revision, _, _, _ = _published_objects(client, db_session)
    now = datetime.now(UTC)
    db_session.add(
        RecruitmentMaster(
            recruiting_authority_id=master.recruiting_authority_id,
            candidate_key=master.candidate_key,
            display_name="Duplicate",
            first_published_at=now,
            last_published_at=now,
            last_verified_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    duplicate_number = RecruitmentMasterRevision(
        recruitment_master_id=revision.recruitment_master_id,
        revision_number=revision.revision_number,
        projection_hash="a" * 64,
        display_name=revision.display_name,
        source_candidate_revision_id=revision.source_candidate_revision_id,
        verification_run_id=revision.verification_run_id,
        revision_confidence_assessment_id=revision.revision_confidence_assessment_id,
        publication_path=revision.publication_path,
        published_at=now,
        verified_at=now,
    )
    db_session.add(duplicate_number)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    duplicate_hash = RecruitmentMasterRevision(
        recruitment_master_id=revision.recruitment_master_id,
        revision_number=revision.revision_number + 1,
        projection_hash=revision.projection_hash,
        display_name=revision.display_name,
        source_candidate_revision_id=revision.source_candidate_revision_id,
        verification_run_id=revision.verification_run_id,
        revision_confidence_assessment_id=revision.revision_confidence_assessment_id,
        publication_path=revision.publication_path,
        published_at=now,
        verified_at=now,
    )
    db_session.add(duplicate_hash)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_master_children_have_database_duplicate_protection(
    client: TestClient, db_session: Session
) -> None:
    master, revision, field, event, change = _published_objects(client, db_session)
    duplicate_field = MasterField(
        master_revision_id=field.master_revision_id,
        field_path=field.field_path,
        value_type=field.value_type,
        value=field.value,
        source_candidate_field_id=field.source_candidate_field_id,
        review_decision_id=field.review_decision_id,
        value_origin=field.value_origin,
    )
    db_session.add(duplicate_field)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    duplicate_event = MasterPublicationEvent(
        recruitment_master_id=master.id,
        master_revision_id=revision.id,
        source_candidate_revision_id=event.source_candidate_revision_id,
        verification_run_id=event.verification_run_id,
        revision_confidence_assessment_id=event.revision_confidence_assessment_id,
        review_case_id=event.review_case_id,
        publication_path=event.publication_path,
        result=event.result,
        published_or_verified_at=event.published_or_verified_at,
    )
    db_session.add(duplicate_event)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    duplicate_change = MasterChange(
        recruitment_master_id=master.id,
        from_master_revision_id=change.from_master_revision_id,
        to_master_revision_id=change.to_master_revision_id,
        field_path=change.field_path,
        change_type=change.change_type,
        old_value_type=change.old_value_type,
        old_value=change.old_value,
        new_value_type=change.new_value_type,
        new_value=change.new_value,
        source_candidate_field_id=change.source_candidate_field_id,
        review_decision_id=change.review_decision_id,
    )
    db_session.add(duplicate_change)
    with pytest.raises(IntegrityError):
        db_session.commit()
