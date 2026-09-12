import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.candidates import RecruitmentCandidate
    from app.models.discovery import DiscoveryRun, SourceDocument


class AuthorityType(enum.StrEnum):
    COMMISSION = "COMMISSION"
    DEPARTMENT = "DEPARTMENT"
    BOARD = "BOARD"
    POLICE = "POLICE"
    AUTONOMOUS_BODY = "AUTONOMOUS_BODY"
    PSU = "PSU"
    UNIVERSITY = "UNIVERSITY"
    OTHER = "OTHER"


class AuthorityStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SourceType(enum.StrEnum):
    RECRUITMENT_INDEX = "RECRUITMENT_INDEX"
    NOTIFICATION_INDEX = "NOTIFICATION_INDEX"
    APPLICATION_PORTAL = "APPLICATION_PORTAL"
    DOCUMENT_LISTING = "DOCUMENT_LISTING"
    OTHER = "OTHER"


class SourceClass(enum.StrEnum):
    AUTHORITATIVE_OFFICIAL = "AUTHORITATIVE_OFFICIAL"
    OFFICIAL_SUPPORTING = "OFFICIAL_SUPPORTING"
    SECONDARY_DISCOVERY_ONLY = "SECONDARY_DISCOVERY_ONLY"


class SourceStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DISABLED = "DISABLED"


def constrained_enum(enum_type: type[enum.Enum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
    )


class RecruitingAuthority(Base):
    __tablename__ = "recruiting_authorities"
    __table_args__ = (UniqueConstraint("code", name="uq_recruiting_authorities_code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    authority_type: Mapped[AuthorityType] = mapped_column(
        constrained_enum(AuthorityType, "ck_recruiting_authorities_type"),
        nullable=False,
    )
    official_website_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[AuthorityStatus] = mapped_column(
        constrained_enum(AuthorityStatus, "ck_recruiting_authorities_status"),
        nullable=False,
        default=AuthorityStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    endpoints: Mapped[list["SourceEndpoint"]] = relationship(back_populates="recruiting_authority")
    recruitment_candidates: Mapped[list["RecruitmentCandidate"]] = relationship(
        back_populates="recruiting_authority"
    )


class SourceEndpoint(Base):
    __tablename__ = "source_endpoints"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_source_endpoints_canonical_url"),
        Index("ix_source_endpoints_authority_id", "recruiting_authority_id"),
        Index("ix_source_endpoints_discovery", "status", "discovery_enabled"),
        Index("ix_source_endpoints_source_type", "source_type"),
        Index("ix_source_endpoints_source_class", "source_class"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruiting_authority_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruiting_authorities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        constrained_enum(SourceType, "ck_source_endpoints_type"),
        nullable=False,
    )
    source_class: Mapped[SourceClass] = mapped_column(
        constrained_enum(SourceClass, "ck_source_endpoints_class"),
        nullable=False,
    )
    status: Mapped[SourceStatus] = mapped_column(
        constrained_enum(SourceStatus, "ck_source_endpoints_status"),
        nullable=False,
        default=SourceStatus.ACTIVE,
    )
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    adapter_key: Mapped[str | None] = mapped_column(String(128))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provenance_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    recruiting_authority: Mapped[RecruitingAuthority] = relationship(back_populates="endpoints")
    discovery_runs: Mapped[list["DiscoveryRun"]] = relationship(back_populates="source_endpoint")
    source_documents: Mapped[list["SourceDocument"]] = relationship(
        back_populates="source_endpoint"
    )
