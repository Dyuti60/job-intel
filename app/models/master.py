import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.candidates import CandidateValueType
from app.models.source_registry import constrained_enum


class RecruitmentMasterStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"


class PublicationPath(enum.StrEnum):
    VERIFIED_NO_REVIEW = "VERIFIED_NO_REVIEW"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    HUMAN_CORRECTED = "HUMAN_CORRECTED"


class MasterFieldValueOrigin(enum.StrEnum):
    CANDIDATE_VERIFIED = "CANDIDATE_VERIFIED"
    HUMAN_APPROVED_AS_IS = "HUMAN_APPROVED_AS_IS"
    HUMAN_CORRECTED = "HUMAN_CORRECTED"


class MasterChangeType(enum.StrEnum):
    ADDED = "ADDED"
    UPDATED = "UPDATED"
    REMOVED = "REMOVED"


class PublicationResult(enum.StrEnum):
    CREATED = "CREATED"
    UNCHANGED = "UNCHANGED"


class RecruitmentMaster(Base):
    __tablename__ = "recruitment_masters"
    __table_args__ = (
        UniqueConstraint(
            "recruiting_authority_id",
            "candidate_key",
            name="uq_recruitment_masters_authority_key",
        ),
        Index("ix_recruitment_masters_status", "status"),
        Index("ix_recruitment_masters_current_revision_id", "current_revision_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruiting_authority_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruiting_authorities.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[RecruitmentMasterStatus] = mapped_column(
        constrained_enum(RecruitmentMasterStatus, "ck_recruitment_masters_status"),
        nullable=False,
        default=RecruitmentMasterStatus.ACTIVE,
    )
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "recruitment_master_revisions.id",
            name="fk_recruitment_masters_current_revision",
            ondelete="RESTRICT",
            use_alter=True,
        )
    )
    first_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    revisions: Mapped[list["RecruitmentMasterRevision"]] = relationship(
        back_populates="recruitment_master",
        foreign_keys="RecruitmentMasterRevision.recruitment_master_id",
        order_by="RecruitmentMasterRevision.revision_number",
    )
    current_revision: Mapped["RecruitmentMasterRevision | None"] = relationship(
        foreign_keys=[current_revision_id], post_update=True
    )


class RecruitmentMasterRevision(Base):
    __tablename__ = "recruitment_master_revisions"
    __table_args__ = (
        UniqueConstraint(
            "recruitment_master_id",
            "revision_number",
            name="uq_master_revisions_master_number",
        ),
        UniqueConstraint(
            "recruitment_master_id",
            "projection_hash",
            name="uq_master_revisions_master_hash",
        ),
        CheckConstraint("revision_number >= 1", name="ck_master_revisions_positive_number"),
        CheckConstraint(
            "length(projection_hash) = 64 AND projection_hash = lower(projection_hash)",
            name="ck_master_revisions_projection_hash",
        ),
        CheckConstraint(
            "(publication_path = 'VERIFIED_NO_REVIEW' AND review_case_id IS NULL) OR "
            "(publication_path IN ('HUMAN_APPROVED', 'HUMAN_CORRECTED') "
            "AND review_case_id IS NOT NULL)",
            name="ck_master_revisions_review_path",
        ),
        Index("ix_master_revisions_candidate_revision_id", "source_candidate_revision_id"),
        Index("ix_master_revisions_verification_run_id", "verification_run_id"),
        Index("ix_master_revisions_confidence_id", "revision_confidence_assessment_id"),
        Index("ix_master_revisions_review_case_id", "review_case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruitment_master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_masters.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    projection_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_candidate_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_candidate_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    verification_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="RESTRICT"), nullable=False
    )
    revision_confidence_assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("revision_confidence_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    review_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_cases.id", ondelete="RESTRICT")
    )
    publication_path: Mapped[PublicationPath] = mapped_column(
        constrained_enum(PublicationPath, "ck_master_revisions_publication_path"), nullable=False
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recruitment_master: Mapped[RecruitmentMaster] = relationship(
        back_populates="revisions", foreign_keys=[recruitment_master_id]
    )
    fields: Mapped[list["MasterField"]] = relationship(
        back_populates="master_revision", order_by="MasterField.field_path"
    )
    posts: Mapped[list["MasterPost"]] = relationship(
        back_populates="master_revision", order_by="MasterPost.ordinal"
    )


class MasterField(Base):
    __tablename__ = "master_fields"
    __table_args__ = (
        UniqueConstraint("master_revision_id", "field_path", name="uq_master_fields_revision_path"),
        UniqueConstraint("id", "master_revision_id", name="uq_master_fields_id_revision"),
        CheckConstraint(
            "(value_origin = 'CANDIDATE_VERIFIED' AND review_decision_id IS NULL) OR "
            "(value_origin IN ('HUMAN_APPROVED_AS_IS', 'HUMAN_CORRECTED') "
            "AND review_decision_id IS NOT NULL)",
            name="ck_master_fields_value_origin_provenance",
        ),
        Index("ix_master_fields_source_candidate_field_id", "source_candidate_field_id"),
        Index("ix_master_fields_review_decision_id", "review_decision_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    master_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_master_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(String(255), nullable=False)
    value_type: Mapped[CandidateValueType] = mapped_column(
        constrained_enum(CandidateValueType, "ck_master_fields_value_type"), nullable=False
    )
    value: Mapped[Any] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True
    )
    source_candidate_field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_fields.id", ondelete="RESTRICT"), nullable=False
    )
    review_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_decisions.id", ondelete="RESTRICT")
    )
    value_origin: Mapped[MasterFieldValueOrigin] = mapped_column(
        constrained_enum(MasterFieldValueOrigin, "ck_master_fields_value_origin"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    master_revision: Mapped[RecruitmentMasterRevision] = relationship(back_populates="fields")


class MasterPost(Base):
    """An approved immutable Post snapshot inside one Master revision."""

    __tablename__ = "master_posts"
    __table_args__ = (
        UniqueConstraint("master_revision_id", "post_key", name="uq_master_posts_revision_key"),
        UniqueConstraint("master_revision_id", "ordinal", name="uq_master_posts_revision_ordinal"),
        UniqueConstraint(
            "master_revision_id", "public_id", name="uq_master_posts_revision_public_id"
        ),
        UniqueConstraint("id", "master_revision_id", name="uq_master_posts_id_revision"),
        CheckConstraint("ordinal >= 1", name="ck_master_posts_positive_ordinal"),
        Index("ix_master_posts_source_post", "source_recruitment_post_id"),
        Index("ix_master_posts_public_id", "public_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    master_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_master_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    source_recruitment_post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_posts.id", ondelete="RESTRICT"), nullable=False
    )
    public_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    post_key: Mapped[str] = mapped_column(String(128), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    master_revision: Mapped[RecruitmentMasterRevision] = relationship(back_populates="posts")
    facts: Mapped[list["MasterPostFact"]] = relationship(
        back_populates="master_post", order_by="MasterPostFact.fact_key"
    )


class MasterPostFact(Base):
    """Post-scoped meaning for an approved MasterField."""

    __tablename__ = "master_post_facts"
    __table_args__ = (
        UniqueConstraint("master_post_id", "fact_key", name="uq_master_post_facts_post_key"),
        UniqueConstraint("master_field_id", name="uq_master_post_facts_master_field"),
        ForeignKeyConstraint(
            ["master_post_id", "master_revision_id"],
            ["master_posts.id", "master_posts.master_revision_id"],
            name="fk_master_post_facts_post_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["master_field_id", "master_revision_id"],
            ["master_fields.id", "master_fields.master_revision_id"],
            name="fk_master_post_facts_field_revision",
            ondelete="RESTRICT",
        ),
        Index("ix_master_post_facts_source_fact", "source_post_fact_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    master_post_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    master_revision_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    master_field_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_post_fact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("post_facts.id", ondelete="RESTRICT"), nullable=False
    )
    fact_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    master_post: Mapped[MasterPost] = relationship(back_populates="facts", overlaps="master_field")
    master_field: Mapped[MasterField] = relationship(overlaps="master_post,facts")


class MasterPublicationEvent(Base):
    __tablename__ = "master_publication_events"
    __table_args__ = (
        UniqueConstraint(
            "revision_confidence_assessment_id", name="uq_master_publication_events_confidence"
        ),
        CheckConstraint(
            "(publication_path = 'VERIFIED_NO_REVIEW' AND review_case_id IS NULL) OR "
            "(publication_path IN ('HUMAN_APPROVED', 'HUMAN_CORRECTED') "
            "AND review_case_id IS NOT NULL)",
            name="ck_master_publication_events_review_path",
        ),
        Index("ix_master_publication_events_master_id", "recruitment_master_id"),
        Index("ix_master_publication_events_revision_id", "master_revision_id"),
        Index("ix_master_publication_events_candidate_revision_id", "source_candidate_revision_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruitment_master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_masters.id", ondelete="RESTRICT"), nullable=False
    )
    master_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_master_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    source_candidate_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_candidate_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    verification_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("verification_runs.id", ondelete="RESTRICT"), nullable=False
    )
    revision_confidence_assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("revision_confidence_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    review_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_cases.id", ondelete="RESTRICT")
    )
    publication_path: Mapped[PublicationPath] = mapped_column(
        constrained_enum(PublicationPath, "ck_master_publication_events_path"), nullable=False
    )
    result: Mapped[PublicationResult] = mapped_column(
        constrained_enum(PublicationResult, "ck_master_publication_events_result"), nullable=False
    )
    published_or_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MasterChange(Base):
    __tablename__ = "master_changes"
    __table_args__ = (
        UniqueConstraint("to_master_revision_id", "field_path", name="uq_master_changes_to_path"),
        CheckConstraint(
            "(change_type = 'ADDED' AND old_value_type IS NULL AND new_value_type IS NOT NULL) OR "
            "(change_type = 'UPDATED' AND old_value_type IS NOT NULL "
            "AND new_value_type IS NOT NULL) OR "
            "(change_type = 'REMOVED' AND old_value_type IS NOT NULL AND new_value_type IS NULL)",
            name="ck_master_changes_value_shape",
        ),
        Index("ix_master_changes_master_id", "recruitment_master_id"),
        Index("ix_master_changes_from_revision_id", "from_master_revision_id"),
        Index("ix_master_changes_source_candidate_field_id", "source_candidate_field_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recruitment_master_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_masters.id", ondelete="RESTRICT"), nullable=False
    )
    from_master_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recruitment_master_revisions.id", ondelete="RESTRICT")
    )
    to_master_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_master_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(String(255), nullable=False)
    change_type: Mapped[MasterChangeType] = mapped_column(
        constrained_enum(MasterChangeType, "ck_master_changes_type"), nullable=False
    )
    old_value_type: Mapped[CandidateValueType | None] = mapped_column(
        constrained_enum(CandidateValueType, "ck_master_changes_old_value_type")
    )
    old_value: Mapped[Any] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True
    )
    new_value_type: Mapped[CandidateValueType | None] = mapped_column(
        constrained_enum(CandidateValueType, "ck_master_changes_new_value_type")
    )
    new_value: Mapped[Any] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True
    )
    source_candidate_field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_fields.id", ondelete="RESTRICT")
    )
    review_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_decisions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
