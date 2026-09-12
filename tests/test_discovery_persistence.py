import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.discovery import (
    DiscoveryObservation,
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoveryTriggerType,
    DocumentType,
    ObservationStatus,
    SourceDocument,
    SourceDocumentStatus,
)
from app.models.source_registry import (
    AuthorityStatus,
    AuthorityType,
    RecruitingAuthority,
    SourceClass,
    SourceEndpoint,
    SourceStatus,
    SourceType,
)


def create_graph(db_session: Session) -> tuple[SourceEndpoint, DiscoveryRun]:
    authority = RecruitingAuthority(
        code="PERSISTENCE",
        name="Persistence Test Authority",
        authority_type=AuthorityType.DEPARTMENT,
        official_website_url="https://persistence.example.gov.in/",
        status=AuthorityStatus.ACTIVE,
    )
    db_session.add(authority)
    db_session.flush()
    endpoint = SourceEndpoint(
        recruiting_authority_id=authority.id,
        name="Persistence endpoint",
        canonical_url="https://persistence.example.gov.in/notices",
        source_type=SourceType.DOCUMENT_LISTING,
        source_class=SourceClass.AUTHORITATIVE_OFFICIAL,
        status=SourceStatus.ACTIVE,
        discovery_enabled=True,
    )
    db_session.add(endpoint)
    db_session.flush()
    run = DiscoveryRun(
        source_endpoint_id=endpoint.id,
        status=DiscoveryRunStatus.RUNNING,
        started_at=datetime.now(UTC),
        trigger_type=DiscoveryTriggerType.MANUAL,
        documents_discovered=0,
        documents_new=0,
        documents_changed=0,
        documents_unchanged=0,
    )
    db_session.add(run)
    db_session.flush()
    return endpoint, run


def make_document(endpoint: SourceEndpoint, run: DiscoveryRun) -> SourceDocument:
    now = datetime.now(UTC)
    return SourceDocument(
        source_endpoint_id=endpoint.id,
        first_discovery_run_id=run.id,
        latest_discovery_run_id=run.id,
        document_url="https://persistence.example.gov.in/notice.pdf",
        normalized_document_url="https://persistence.example.gov.in/notice.pdf",
        document_type=DocumentType.PDF,
        content_type="application/pdf",
        content_hash="a" * 64,
        content_length=10,
        first_seen_at=now,
        last_seen_at=now,
        retrieved_at=now,
        status=SourceDocumentStatus.ACTIVE,
    )


def test_document_version_identity_unique_constraint(db_session: Session) -> None:
    endpoint, run = create_graph(db_session)
    db_session.add_all([make_document(endpoint, run), make_document(endpoint, run)])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_run_document_observation_unique_constraint(db_session: Session) -> None:
    endpoint, run = create_graph(db_session)
    document = make_document(endpoint, run)
    db_session.add(document)
    db_session.flush()
    now = datetime.now(UTC)
    values = {
        "discovery_run_id": run.id,
        "source_document_id": document.id,
        "observation_status": ObservationStatus.NEW,
        "observed_url": document.document_url,
        "observed_at": now,
        "retrieved_at": now,
    }
    db_session.add_all(
        [
            DiscoveryObservation(id=uuid.uuid4(), **values),
            DiscoveryObservation(id=uuid.uuid4(), **values),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_negative_run_counter_is_rejected_by_database(db_session: Session) -> None:
    _, run = create_graph(db_session)
    run.documents_discovered = -1

    with pytest.raises(IntegrityError):
        db_session.commit()
