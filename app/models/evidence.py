import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.source_registry import constrained_enum

if TYPE_CHECKING:
    from app.models.discovery import SourceDocument


class EvidenceType(enum.StrEnum):
    TEXT_EXCERPT = "TEXT_EXCERPT"
    TABLE_FRAGMENT = "TABLE_FRAGMENT"
    STRUCTURED_FRAGMENT = "STRUCTURED_FRAGMENT"
    DOCUMENT_METADATA = "DOCUMENT_METADATA"
    OTHER = "OTHER"


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint(
            "source_document_id",
            "evidence_hash",
            name="uq_evidence_document_hash",
        ),
        UniqueConstraint(
            "id",
            "source_document_id",
            name="uq_evidence_id_source_document",
        ),
        CheckConstraint(
            "length(evidence_hash) = 64 AND evidence_hash = lower(evidence_hash)",
            name="ck_evidence_hash_format",
        ),
        Index("ix_evidence_type", "evidence_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        constrained_enum(EvidenceType, "ck_evidence_type"),
        nullable=False,
    )
    source_locator: Mapped[str | None] = mapped_column(String(1024))
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source_document: Mapped["SourceDocument"] = relationship()


class CandidateFieldEvidence(Base):
    __tablename__ = "candidate_field_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_field_id", "source_document_id"],
            ["candidate_fields.id", "candidate_fields.source_document_id"],
            name="fk_candidate_field_evidence_field_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "source_document_id"],
            ["evidence.id", "evidence.source_document_id"],
            name="fk_candidate_field_evidence_evidence_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "candidate_field_id",
            "evidence_id",
            name="uq_candidate_field_evidence_link",
        ),
        Index("ix_candidate_field_evidence_evidence_id", "evidence_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    candidate_field_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    evidence_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_document_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
