"""Create the approved Recruitment Master and publisher audit schema.

Revision ID: 20260912_0009
Revises: 20260912_0008
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260912_0009"
down_revision: str | None = "20260912_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recruitment_masters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruiting_authority_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')",
            name="ck_recruitment_masters_status",
        ),
        sa.ForeignKeyConstraint(
            ["recruiting_authority_id"], ["recruiting_authorities.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recruiting_authority_id",
            "candidate_key",
            name="uq_recruitment_masters_authority_key",
        ),
    )
    op.create_index("ix_recruitment_masters_status", "recruitment_masters", ["status"])
    op.create_index(
        "ix_recruitment_masters_current_revision_id",
        "recruitment_masters",
        ["current_revision_id"],
    )

    op.create_table(
        "recruitment_master_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruitment_master_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("projection_hash", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("source_candidate_revision_id", sa.Uuid(), nullable=False),
        sa.Column("verification_run_id", sa.Uuid(), nullable=False),
        sa.Column("revision_confidence_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("review_case_id", sa.Uuid(), nullable=True),
        sa.Column("publication_path", sa.String(length=18), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("revision_number >= 1", name="ck_master_revisions_positive_number"),
        sa.CheckConstraint(
            "length(projection_hash) = 64 AND projection_hash = lower(projection_hash)",
            name="ck_master_revisions_projection_hash",
        ),
        sa.CheckConstraint(
            "publication_path IN ('VERIFIED_NO_REVIEW', 'HUMAN_APPROVED', 'HUMAN_CORRECTED')",
            name="ck_master_revisions_publication_path",
        ),
        sa.CheckConstraint(
            "(publication_path = 'VERIFIED_NO_REVIEW' AND review_case_id IS NULL) OR "
            "(publication_path IN ('HUMAN_APPROVED', 'HUMAN_CORRECTED') "
            "AND review_case_id IS NOT NULL)",
            name="ck_master_revisions_review_path",
        ),
        sa.ForeignKeyConstraint(
            ["recruitment_master_id"], ["recruitment_masters.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_candidate_revision_id"],
            ["recruitment_candidate_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_run_id"], ["verification_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["revision_confidence_assessment_id"],
            ["revision_confidence_assessments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["review_case_id"], ["review_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recruitment_master_id",
            "revision_number",
            name="uq_master_revisions_master_number",
        ),
        sa.UniqueConstraint(
            "recruitment_master_id",
            "projection_hash",
            name="uq_master_revisions_master_hash",
        ),
    )
    op.create_index(
        "ix_master_revisions_candidate_revision_id",
        "recruitment_master_revisions",
        ["source_candidate_revision_id"],
    )
    op.create_index(
        "ix_master_revisions_verification_run_id",
        "recruitment_master_revisions",
        ["verification_run_id"],
    )
    op.create_index(
        "ix_master_revisions_confidence_id",
        "recruitment_master_revisions",
        ["revision_confidence_assessment_id"],
    )
    op.create_index(
        "ix_master_revisions_review_case_id",
        "recruitment_master_revisions",
        ["review_case_id"],
    )
    op.create_foreign_key(
        "fk_recruitment_masters_current_revision",
        "recruitment_masters",
        "recruitment_master_revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "master_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("master_revision_id", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=False),
        sa.Column("value_type", sa.String(length=8), nullable=False),
        sa.Column(
            "value", postgresql.JSONB(astext_type=sa.Text(), none_as_null=True), nullable=True
        ),
        sa.Column("source_candidate_field_id", sa.Uuid(), nullable=False),
        sa.Column("review_decision_id", sa.Uuid(), nullable=True),
        sa.Column("value_origin", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "value_type IN ('STRING', 'INTEGER', 'DECIMAL', 'BOOLEAN', "
            "'DATE', 'DATETIME', 'JSON', 'NULL')",
            name="ck_master_fields_value_type",
        ),
        sa.CheckConstraint(
            "value_origin IN ('CANDIDATE_VERIFIED', 'HUMAN_APPROVED_AS_IS', 'HUMAN_CORRECTED')",
            name="ck_master_fields_value_origin",
        ),
        sa.CheckConstraint(
            "(value_origin = 'CANDIDATE_VERIFIED' AND review_decision_id IS NULL) OR "
            "(value_origin IN ('HUMAN_APPROVED_AS_IS', 'HUMAN_CORRECTED') "
            "AND review_decision_id IS NOT NULL)",
            name="ck_master_fields_value_origin_provenance",
        ),
        sa.ForeignKeyConstraint(
            ["master_revision_id"], ["recruitment_master_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_candidate_field_id"], ["candidate_fields.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["review_decision_id"], ["review_decisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "master_revision_id", "field_path", name="uq_master_fields_revision_path"
        ),
    )
    op.create_index(
        "ix_master_fields_source_candidate_field_id", "master_fields", ["source_candidate_field_id"]
    )
    op.create_index("ix_master_fields_review_decision_id", "master_fields", ["review_decision_id"])

    op.create_table(
        "master_publication_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruitment_master_id", sa.Uuid(), nullable=False),
        sa.Column("master_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_candidate_revision_id", sa.Uuid(), nullable=False),
        sa.Column("verification_run_id", sa.Uuid(), nullable=False),
        sa.Column("revision_confidence_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("review_case_id", sa.Uuid(), nullable=True),
        sa.Column("publication_path", sa.String(length=18), nullable=False),
        sa.Column("result", sa.String(length=9), nullable=False),
        sa.Column("published_or_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "publication_path IN ('VERIFIED_NO_REVIEW', 'HUMAN_APPROVED', 'HUMAN_CORRECTED')",
            name="ck_master_publication_events_path",
        ),
        sa.CheckConstraint(
            "result IN ('CREATED', 'UNCHANGED')", name="ck_master_publication_events_result"
        ),
        sa.CheckConstraint(
            "(publication_path = 'VERIFIED_NO_REVIEW' AND review_case_id IS NULL) OR "
            "(publication_path IN ('HUMAN_APPROVED', 'HUMAN_CORRECTED') "
            "AND review_case_id IS NOT NULL)",
            name="ck_master_publication_events_review_path",
        ),
        sa.ForeignKeyConstraint(
            ["recruitment_master_id"], ["recruitment_masters.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["master_revision_id"], ["recruitment_master_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_candidate_revision_id"],
            ["recruitment_candidate_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_run_id"], ["verification_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["revision_confidence_assessment_id"],
            ["revision_confidence_assessments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["review_case_id"], ["review_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_confidence_assessment_id", name="uq_master_publication_events_confidence"
        ),
    )
    op.create_index(
        "ix_master_publication_events_master_id",
        "master_publication_events",
        ["recruitment_master_id"],
    )
    op.create_index(
        "ix_master_publication_events_revision_id",
        "master_publication_events",
        ["master_revision_id"],
    )
    op.create_index(
        "ix_master_publication_events_candidate_revision_id",
        "master_publication_events",
        ["source_candidate_revision_id"],
    )

    op.create_table(
        "master_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruitment_master_id", sa.Uuid(), nullable=False),
        sa.Column("from_master_revision_id", sa.Uuid(), nullable=True),
        sa.Column("to_master_revision_id", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=False),
        sa.Column("change_type", sa.String(length=7), nullable=False),
        sa.Column("old_value_type", sa.String(length=8), nullable=True),
        sa.Column(
            "old_value", postgresql.JSONB(astext_type=sa.Text(), none_as_null=True), nullable=True
        ),
        sa.Column("new_value_type", sa.String(length=8), nullable=True),
        sa.Column(
            "new_value", postgresql.JSONB(astext_type=sa.Text(), none_as_null=True), nullable=True
        ),
        sa.Column("source_candidate_field_id", sa.Uuid(), nullable=False),
        sa.Column("review_decision_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "change_type IN ('ADDED', 'UPDATED', 'REMOVED')", name="ck_master_changes_type"
        ),
        sa.CheckConstraint(
            "old_value_type IS NULL OR old_value_type IN "
            "('STRING', 'INTEGER', 'DECIMAL', 'BOOLEAN', 'DATE', 'DATETIME', 'JSON', 'NULL')",
            name="ck_master_changes_old_value_type",
        ),
        sa.CheckConstraint(
            "new_value_type IS NULL OR new_value_type IN "
            "('STRING', 'INTEGER', 'DECIMAL', 'BOOLEAN', 'DATE', 'DATETIME', 'JSON', 'NULL')",
            name="ck_master_changes_new_value_type",
        ),
        sa.CheckConstraint(
            "(change_type = 'ADDED' AND old_value_type IS NULL AND new_value_type IS NOT NULL) OR "
            "(change_type = 'UPDATED' AND old_value_type IS NOT NULL "
            "AND new_value_type IS NOT NULL) OR "
            "(change_type = 'REMOVED' AND old_value_type IS NOT NULL AND new_value_type IS NULL)",
            name="ck_master_changes_value_shape",
        ),
        sa.ForeignKeyConstraint(
            ["recruitment_master_id"], ["recruitment_masters.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["from_master_revision_id"],
            ["recruitment_master_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_master_revision_id"], ["recruitment_master_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_candidate_field_id"], ["candidate_fields.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["review_decision_id"], ["review_decisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "to_master_revision_id", "field_path", name="uq_master_changes_to_path"
        ),
    )
    op.create_index("ix_master_changes_master_id", "master_changes", ["recruitment_master_id"])
    op.create_index(
        "ix_master_changes_from_revision_id", "master_changes", ["from_master_revision_id"]
    )
    op.create_index(
        "ix_master_changes_source_candidate_field_id",
        "master_changes",
        ["source_candidate_field_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_master_changes_source_candidate_field_id", table_name="master_changes")
    op.drop_index("ix_master_changes_from_revision_id", table_name="master_changes")
    op.drop_index("ix_master_changes_master_id", table_name="master_changes")
    op.drop_table("master_changes")
    op.drop_index(
        "ix_master_publication_events_candidate_revision_id",
        table_name="master_publication_events",
    )
    op.drop_index(
        "ix_master_publication_events_revision_id", table_name="master_publication_events"
    )
    op.drop_index("ix_master_publication_events_master_id", table_name="master_publication_events")
    op.drop_table("master_publication_events")
    op.drop_index("ix_master_fields_review_decision_id", table_name="master_fields")
    op.drop_index("ix_master_fields_source_candidate_field_id", table_name="master_fields")
    op.drop_table("master_fields")
    op.drop_constraint(
        "fk_recruitment_masters_current_revision", "recruitment_masters", type_="foreignkey"
    )
    op.drop_index("ix_master_revisions_review_case_id", table_name="recruitment_master_revisions")
    op.drop_index("ix_master_revisions_confidence_id", table_name="recruitment_master_revisions")
    op.drop_index(
        "ix_master_revisions_verification_run_id", table_name="recruitment_master_revisions"
    )
    op.drop_index(
        "ix_master_revisions_candidate_revision_id", table_name="recruitment_master_revisions"
    )
    op.drop_table("recruitment_master_revisions")
    op.drop_index("ix_recruitment_masters_current_revision_id", table_name="recruitment_masters")
    op.drop_index("ix_recruitment_masters_status", table_name="recruitment_masters")
    op.drop_table("recruitment_masters")
