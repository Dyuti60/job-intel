import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidates import CandidateValueType
from app.models.source_registry import SourceClass
from app.models.verification import (
    EvidenceAssessmentType,
    FieldVerification,
    FieldVerificationStatus,
    VerificationEvidenceAssessment,
    VerificationRun,
)
from tests.factories import (
    add_verification_assessment,
    create_evidence,
    create_field_verification,
    create_ready_candidate_revision,
    create_verification_run,
    start_verification_run,
)


def running_graph(client: TestClient) -> tuple[dict, dict, dict, dict]:
    _, document, _, revision = create_ready_candidate_revision(client)
    run = create_verification_run(client, revision["id"])
    start_verification_run(client, run["id"])
    verification = create_field_verification(
        client, run["id"], revision["fields"][0]["id"]
    )
    return document, revision, run, verification


def test_field_verification_run_field_unique_constraint(
    client: TestClient, db_session: Session
) -> None:
    _, revision, run, verification = running_graph(client)
    db_session.add(
        FieldVerification(
            verification_run_id=uuid.UUID(run["id"]),
            candidate_field_id=uuid.UUID(verification["candidate_field_id"]),
            candidate_field_path_snapshot=verification[
                "candidate_field_path_snapshot"
            ],
            candidate_field_value_snapshot=verification[
                "candidate_field_value_snapshot"
            ],
            candidate_field_type_snapshot=CandidateValueType(
                verification["candidate_field_type_snapshot"]
            ),
            status=FieldVerificationStatus.PENDING,
            authoritative_support_count=0,
            official_support_count=0,
            secondary_support_count=0,
            authoritative_conflict_count=0,
            official_conflict_count=0,
            secondary_conflict_count=0,
            evidence_count=0,
        )
    )

    assert revision["fields"]
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_assessment_field_evidence_unique_constraint(
    client: TestClient, db_session: Session
) -> None:
    document, _, _, verification = running_graph(client)
    evidence = create_evidence(client, document["id"])
    current = add_verification_assessment(
        client,
        verification["id"],
        evidence["id"],
        "SUPPORTS",
        asserted_value=verification["candidate_field_value_snapshot"],
        asserted_value_type=verification["candidate_field_type_snapshot"],
    )
    db_session.add(
        VerificationEvidenceAssessment(
            field_verification_id=uuid.UUID(verification["id"]),
            evidence_id=uuid.UUID(evidence["id"]),
            assessment=EvidenceAssessmentType.SUPPORTS,
            asserted_value=verification["candidate_field_value_snapshot"],
            asserted_value_type=CandidateValueType(
                verification["candidate_field_type_snapshot"]
            ),
            source_class_snapshot=SourceClass.AUTHORITATIVE_OFFICIAL,
        )
    )

    assert len(current["assessments"]) == 1
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_negative_run_counter_is_rejected_by_database(
    client: TestClient, db_session: Session
) -> None:
    _, _, run, _ = running_graph(client)
    persisted = db_session.get(VerificationRun, uuid.UUID(run["id"]))
    assert persisted is not None
    persisted.fields_confirmed = -1

    with pytest.raises(IntegrityError):
        db_session.commit()
