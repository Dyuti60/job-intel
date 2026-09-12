"""Create candidate evidence and field associations.

Revision ID: 20260912_0005
Revises: 20260912_0004
Create Date: 2026-09-12
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260912_0005"
down_revision: str | Sequence[str] | None = "20260912_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_candidate_fields_id_source_document",
        "candidate_fields",
        ["id", "source_document_id"],
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "evidence_type",
            sa.Enum(
                "TEXT_EXCERPT",
                "TABLE_FRAGMENT",
                "STRUCTURED_FRAGMENT",
                "DOCUMENT_METADATA",
                "OTHER",
                name="ck_evidence_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_locator", sa.String(length=1024), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(evidence_hash) = 64 AND evidence_hash = lower(evidence_hash)",
            name="ck_evidence_hash_format",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            name="fk_evidence_source_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_document_id",
            "evidence_hash",
            name="uq_evidence_document_hash",
        ),
        sa.UniqueConstraint(
            "id",
            "source_document_id",
            name="uq_evidence_id_source_document",
        ),
    )
    op.create_index("ix_evidence_type", "evidence", ["evidence_type"])

    op.create_table(
        "candidate_field_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_field_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_field_id", "source_document_id"],
            ["candidate_fields.id", "candidate_fields.source_document_id"],
            name="fk_candidate_field_evidence_field_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id", "source_document_id"],
            ["evidence.id", "evidence.source_document_id"],
            name="fk_candidate_field_evidence_evidence_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_field_id",
            "evidence_id",
            name="uq_candidate_field_evidence_link",
        ),
    )
    op.create_index(
        "ix_candidate_field_evidence_evidence_id",
        "candidate_field_evidence",
        ["evidence_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_field_evidence_evidence_id",
        table_name="candidate_field_evidence",
    )
    op.drop_table("candidate_field_evidence")
    op.drop_index("ix_evidence_type", table_name="evidence")
    op.drop_table("evidence")
    op.drop_constraint(
        "uq_candidate_fields_id_source_document",
        "candidate_fields",
        type_="unique",
    )
