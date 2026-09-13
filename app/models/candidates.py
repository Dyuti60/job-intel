import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.source_registry import constrained_enum

if TYPE_CHECKING:
    from app.models.discovery import SourceDocument
    from app.models.source_registry import RecruitingAuthority


class AdvertisementSplitStatus(enum.StrEnum):
    LEGACY_UNSPLIT = "LEGACY_UNSPLIT"
    EXPLICIT = "EXPLICIT"
    AMBIGUOUS = "AMBIGUOUS"


class CandidateStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_VERIFICATION = "READY_FOR_VERIFICATION"
    DISCARDED = "DISCARDED"


class CandidateValueType(enum.StrEnum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"
    JSON = "JSON"
    NULL = "NULL"


class RecruitmentCandidate(Base):
    __tablename__ = "recruitment_candidates"
    __table_args__ = (
        UniqueConstraint(
            "recruiting_authority_id",
            "candidate_key",
            name="uq_recruitment_candidates_authority_key",
        ),
        Index("ix_recruitment_candidates_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruiting_authority_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruiting_authorities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    candidate_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[CandidateStatus] = mapped_column(
        constrained_enum(CandidateStatus, "ck_recruitment_candidates_status"),
        nullable=False,
        default=CandidateStatus.DRAFT,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    recruiting_authority: Mapped["RecruitingAuthority"] = relationship(
        back_populates="recruitment_candidates"
    )
    revisions: Mapped[list["RecruitmentCandidateRevision"]] = relationship(
        back_populates="recruitment_candidate",
        order_by="RecruitmentCandidateRevision.revision_number",
    )
    advertisement: Mapped["Advertisement | None"] = relationship(
        back_populates="recruitment_candidate", uselist=False
    )

    @property
    def revision_count(self) -> int:
        return len(self.revisions)

    @property
    def latest_revision_number(self) -> int | None:
        return self.revisions[-1].revision_number if self.revisions else None


class RecruitmentCandidateRevision(Base):
    __tablename__ = "recruitment_candidate_revisions"
    __table_args__ = (
        UniqueConstraint(
            "recruitment_candidate_id",
            "revision_number",
            name="uq_candidate_revisions_candidate_number",
        ),
        UniqueConstraint(
            "recruitment_candidate_id",
            "revision_hash",
            name="uq_candidate_revisions_candidate_hash",
        ),
        UniqueConstraint(
            "id",
            "source_document_id",
            name="uq_candidate_revisions_id_source_document",
        ),
        CheckConstraint(
            "revision_number >= 1",
            name="ck_candidate_revisions_positive_number",
        ),
        Index("ix_candidate_revisions_source_document_id", "source_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruitment_candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_method: Mapped[str | None] = mapped_column(String(128))
    extraction_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recruitment_candidate: Mapped[RecruitmentCandidate] = relationship(
        back_populates="revisions"
    )
    source_document: Mapped["SourceDocument"] = relationship(
        back_populates="candidate_revisions"
    )
    fields: Mapped[list["CandidateField"]] = relationship(
        back_populates="candidate_revision",
        order_by="CandidateField.field_path",
    )
    advertisement_revision: Mapped["AdvertisementRevision | None"] = relationship(
        back_populates="candidate_revision", uselist=False
    )


class CandidateField(Base):
    __tablename__ = "candidate_fields"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_revision_id", "source_document_id"],
            [
                "recruitment_candidate_revisions.id",
                "recruitment_candidate_revisions.source_document_id",
            ],
            name="fk_candidate_fields_revision_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "candidate_revision_id",
            "field_path",
            name="uq_candidate_fields_revision_path",
        ),
        UniqueConstraint(
            "id",
            "source_document_id",
            name="uq_candidate_fields_id_source_document",
        ),
        UniqueConstraint(
            "id",
            "candidate_revision_id",
            name="uq_candidate_fields_id_revision",
        ),
        Index("ix_candidate_fields_field_path", "field_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_revision_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    field_path: Mapped[str] = mapped_column(String(255), nullable=False)
    value_type: Mapped[CandidateValueType] = mapped_column(
        constrained_enum(CandidateValueType, "ck_candidate_fields_value_type"),
        nullable=False,
    )
    value: Mapped[Any] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    raw_value: Mapped[str | None] = mapped_column(Text)
    source_locator: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    candidate_revision: Mapped[RecruitmentCandidateRevision] = relationship(
        back_populates="fields",
        foreign_keys=[candidate_revision_id, source_document_id],
    )


class Advertisement(Base):
    """Stable advertisement identity layered over the historical candidate identity."""

    __tablename__ = "advertisements"
    __table_args__ = (
        UniqueConstraint(
            "recruitment_candidate_id", name="uq_advertisements_recruitment_candidate"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruitment_candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_candidates.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recruitment_candidate: Mapped[RecruitmentCandidate] = relationship(
        back_populates="advertisement"
    )
    revisions: Mapped[list["AdvertisementRevision"]] = relationship(
        back_populates="advertisement", order_by="AdvertisementRevision.created_at"
    )


class AdvertisementRevision(Base):
    """Immutable post-splitting interpretation of one immutable candidate revision."""

    __tablename__ = "advertisement_revisions"
    __table_args__ = (
        UniqueConstraint(
            "candidate_revision_id", name="uq_advertisement_revisions_candidate_revision"
        ),
        UniqueConstraint(
            "id", "candidate_revision_id", name="uq_advertisement_revisions_id_candidate_revision"
        ),
        CheckConstraint(
            "(split_status = 'EXPLICIT' AND detected_post_count >= 1) OR "
            "(split_status IN ('LEGACY_UNSPLIT', 'AMBIGUOUS') "
            "AND detected_post_count IS NULL)",
            name="ck_advertisement_revisions_split_shape",
        ),
        Index("ix_advertisement_revisions_advertisement", "advertisement_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    advertisement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("advertisements.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_candidate_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    split_status: Mapped[AdvertisementSplitStatus] = mapped_column(
        constrained_enum(AdvertisementSplitStatus, "ck_advertisement_revisions_split_status"),
        nullable=False,
    )
    detected_post_count: Mapped[int | None] = mapped_column(Integer)
    split_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    advertisement: Mapped[Advertisement] = relationship(back_populates="revisions")
    candidate_revision: Mapped[RecruitmentCandidateRevision] = relationship(
        back_populates="advertisement_revision"
    )
    posts: Mapped[list["RecruitmentPost"]] = relationship(
        back_populates="advertisement_revision", order_by="RecruitmentPost.ordinal"
    )


class RecruitmentPost(Base):
    """One explicitly supported post detected inside an advertisement revision."""

    __tablename__ = "recruitment_posts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["advertisement_revision_id", "candidate_revision_id"],
            ["advertisement_revisions.id", "advertisement_revisions.candidate_revision_id"],
            name="fk_recruitment_posts_advertisement_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "advertisement_revision_id", "post_key", name="uq_recruitment_posts_revision_key"
        ),
        UniqueConstraint(
            "advertisement_revision_id", "ordinal", name="uq_recruitment_posts_revision_ordinal"
        ),
        UniqueConstraint(
            "id", "candidate_revision_id", name="uq_recruitment_posts_id_candidate_revision"
        ),
        CheckConstraint("ordinal >= 1", name="ck_recruitment_posts_positive_ordinal"),
        Index("ix_recruitment_posts_candidate_revision", "candidate_revision_id"),
        Index("ix_recruitment_posts_normalized_name", "normalized_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    advertisement_revision_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    candidate_revision_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    post_key: Mapped[str] = mapped_column(String(128), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_locator: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    advertisement_revision: Mapped[AdvertisementRevision] = relationship(
        back_populates="posts", foreign_keys=[advertisement_revision_id, candidate_revision_id]
    )
    facts: Mapped[list["PostFact"]] = relationship(
        back_populates="recruitment_post", order_by="PostFact.fact_key"
    )


class PostFact(Base):
    """Post-scoped meaning for a CandidateField with its full evidence chain intact."""

    __tablename__ = "post_facts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["recruitment_post_id", "candidate_revision_id"],
            ["recruitment_posts.id", "recruitment_posts.candidate_revision_id"],
            name="fk_post_facts_recruitment_post",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["candidate_field_id", "candidate_revision_id"],
            ["candidate_fields.id", "candidate_fields.candidate_revision_id"],
            name="fk_post_facts_candidate_field",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("candidate_field_id", name="uq_post_facts_candidate_field"),
        UniqueConstraint(
            "recruitment_post_id", "fact_key", name="uq_post_facts_post_key"
        ),
        Index("ix_post_facts_candidate_revision", "candidate_revision_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruitment_post_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    candidate_revision_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    candidate_field_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    fact_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recruitment_post: Mapped[RecruitmentPost] = relationship(
        back_populates="facts", foreign_keys=[recruitment_post_id, candidate_revision_id]
    )
    candidate_field: Mapped[CandidateField] = relationship(
        foreign_keys=[candidate_field_id, candidate_revision_id],
        overlaps="facts,recruitment_post",
    )
