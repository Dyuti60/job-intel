"""Create recruitment candidates, revisions, and fields.

Revision ID: 20260912_0004
Revises: 20260912_0003
Create Date: 2026-09-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260912_0004"
down_revision: str | Sequence[str] | None = "20260912_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recruitment_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruiting_authority_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "READY_FOR_VERIFICATION",
                "DISCARDED",
                name="ck_recruitment_candidates_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["recruiting_authority_id"],
            ["recruiting_authorities.id"],
            name="fk_recruitment_candidates_authority",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recruiting_authority_id",
            "candidate_key",
            name="uq_recruitment_candidates_authority_key",
        ),
    )
    op.create_index(
        "ix_recruitment_candidates_status",
        "recruitment_candidates",
        ["status"],
    )

    op.create_table(
        "recruitment_candidate_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruitment_candidate_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("revision_hash", sa.String(length=64), nullable=False),
        sa.Column("extraction_method", sa.String(length=128), nullable=True),
        sa.Column("extraction_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name="ck_candidate_revisions_positive_number",
        ),
        sa.ForeignKeyConstraint(
            ["recruitment_candidate_id"],
            ["recruitment_candidates.id"],
            name="fk_candidate_revisions_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            name="fk_candidate_revisions_source_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recruitment_candidate_id",
            "revision_hash",
            name="uq_candidate_revisions_candidate_hash",
        ),
        sa.UniqueConstraint(
            "recruitment_candidate_id",
            "revision_number",
            name="uq_candidate_revisions_candidate_number",
        ),
        sa.UniqueConstraint(
            "id",
            "source_document_id",
            name="uq_candidate_revisions_id_source_document",
        ),
    )
    op.create_index(
        "ix_candidate_revisions_source_document_id",
        "recruitment_candidate_revisions",
        ["source_document_id"],
    )

    op.create_table(
        "candidate_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=False),
        sa.Column(
            "value_type",
            sa.Enum(
                "STRING",
                "INTEGER",
                "DECIMAL",
                "BOOLEAN",
                "DATE",
                "DATETIME",
                "JSON",
                "NULL",
                name="ck_candidate_fields_value_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("source_locator", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_revision_id", "source_document_id"],
            [
                "recruitment_candidate_revisions.id",
                "recruitment_candidate_revisions.source_document_id",
            ],
            name="fk_candidate_fields_revision_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            name="fk_candidate_fields_source_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_revision_id",
            "field_path",
            name="uq_candidate_fields_revision_path",
        ),
    )
    op.create_index(
        "ix_candidate_fields_field_path",
        "candidate_fields",
        ["field_path"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_fields_field_path", table_name="candidate_fields")
    op.drop_table("candidate_fields")
    op.drop_index(
        "ix_candidate_revisions_source_document_id",
        table_name="recruitment_candidate_revisions",
    )
    op.drop_table("recruitment_candidate_revisions")
    op.drop_index(
        "ix_recruitment_candidates_status",
        table_name="recruitment_candidates",
    )
    op.drop_table("recruitment_candidates")
