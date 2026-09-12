import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidates import (
    CandidateField,
    CandidateStatus,
    CandidateValueType,
    RecruitmentCandidate,
    RecruitmentCandidateRevision,
)
from tests.factories import (
    create_authority,
    create_candidate,
    create_discovery_source,
    create_revision,
    create_run,
    observe_document,
)


def test_candidate_identity_unique_constraint(
    client: TestClient, db_session: Session
) -> None:
    authority = create_authority(client)
    values = {
        "recruiting_authority_id": uuid.UUID(authority["id"]),
        "candidate_key": "DATABASE_UNIQUE_KEY",
        "display_name": "Database uniqueness test",
        "status": CandidateStatus.DRAFT,
    }
    db_session.add_all(
        [
            RecruitmentCandidate(id=uuid.uuid4(), **values),
            RecruitmentCandidate(id=uuid.uuid4(), **values),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_revision_number_and_hash_unique_constraints(
    client: TestClient, db_session: Session
) -> None:
    authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    candidate = create_candidate(client, authority["id"])
    revision = create_revision(client, candidate["id"], document["id"])
    db_session.add(
        RecruitmentCandidateRevision(
            recruitment_candidate_id=uuid.UUID(candidate["id"]),
            source_document_id=uuid.UUID(document["id"]),
            revision_number=revision["revision_number"],
            revision_hash=revision["revision_hash"],
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_candidate_field_path_unique_constraint(
    client: TestClient, db_session: Session
) -> None:
    authority, endpoint = create_discovery_source(client)
    run = create_run(client, endpoint["id"])
    document = observe_document(client, run["id"])["document"]
    candidate = create_candidate(client, authority["id"])
    revision = create_revision(client, candidate["id"], document["id"])
    db_session.add(
        CandidateField(
            candidate_revision_id=uuid.UUID(revision["id"]),
            source_document_id=uuid.UUID(document["id"]),
            field_path="vacancies.total",
            value_type=CandidateValueType.INTEGER,
            value=99,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_candidate_field_source_must_match_revision_source(
    client: TestClient, db_session: Session
) -> None:
    authority, endpoint = create_discovery_source(client)
    first_run = create_run(client, endpoint["id"])
    first_document = observe_document(client, first_run["id"], content_text="first")[
        "document"
    ]
    second_run = create_run(client, endpoint["id"])
    second_document = observe_document(client, second_run["id"], content_text="second")[
        "document"
    ]
    candidate = create_candidate(client, authority["id"])
    revision = create_revision(client, candidate["id"], first_document["id"])
    db_session.add(
        CandidateField(
            candidate_revision_id=uuid.UUID(revision["id"]),
            source_document_id=uuid.UUID(second_document["id"]),
            field_path="notification.number",
            value_type=CandidateValueType.STRING,
            value="Mismatch",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
