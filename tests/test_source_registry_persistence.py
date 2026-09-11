import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.source_registry import (
    AuthorityStatus,
    AuthorityType,
    RecruitingAuthority,
    SourceClass,
    SourceEndpoint,
    SourceStatus,
    SourceType,
)


def make_authority(code: str) -> RecruitingAuthority:
    return RecruitingAuthority(
        code=code,
        name=f"{code} Authority",
        authority_type=AuthorityType.DEPARTMENT,
        official_website_url=f"https://{code.lower()}.example.gov.in/",
        status=AuthorityStatus.ACTIVE,
    )


def test_authority_code_unique_constraint(db_session: Session) -> None:
    db_session.add_all([make_authority("DUPLICATE"), make_authority("DUPLICATE")])

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_endpoint_url_unique_constraint(db_session: Session) -> None:
    authority = make_authority("OWNER")
    db_session.add(authority)
    db_session.flush()
    common = {
        "recruiting_authority_id": authority.id,
        "source_type": SourceType.RECRUITMENT_INDEX,
        "source_class": SourceClass.AUTHORITATIVE_OFFICIAL,
        "status": SourceStatus.ACTIVE,
        "discovery_enabled": True,
    }
    db_session.add_all(
        [
            SourceEndpoint(
                id=uuid.uuid4(),
                name="First",
                canonical_url="https://example.gov.in/recruitment",
                **common,
            ),
            SourceEndpoint(
                id=uuid.uuid4(),
                name="Second",
                canonical_url="https://example.gov.in/recruitment",
                **common,
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
