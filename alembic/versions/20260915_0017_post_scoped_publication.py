"""Add Post scope to immutable publication events.

Revision ID: 20260915_0017
Revises: 20260914_0016
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260915_0017"
down_revision: str | Sequence[str] | None = "20260914_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_master_publication_events_confidence",
        "master_publication_events",
        type_="unique",
    )
    op.add_column(
        "master_publication_events",
        sa.Column("post_key", sa.String(length=128)),
    )
    op.create_check_constraint(
        "ck_master_publication_events_post_path",
        "master_publication_events",
        "post_key IS NULL OR publication_path IN ('HUMAN_APPROVED', 'HUMAN_CORRECTED')",
    )
    op.create_index(
        "uq_master_publication_events_confidence_full",
        "master_publication_events",
        ["revision_confidence_assessment_id"],
        unique=True,
        postgresql_where=sa.text("post_key IS NULL"),
    )
    op.create_index(
        "uq_master_publication_events_confidence_post",
        "master_publication_events",
        ["revision_confidence_assessment_id", "post_key"],
        unique=True,
        postgresql_where=sa.text("post_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_master_publication_events_confidence_post",
        table_name="master_publication_events",
    )
    op.drop_index(
        "uq_master_publication_events_confidence_full",
        table_name="master_publication_events",
    )
    op.drop_constraint(
        "ck_master_publication_events_post_path",
        "master_publication_events",
        type_="check",
    )
    op.drop_column("master_publication_events", "post_key")
    op.create_unique_constraint(
        "uq_master_publication_events_confidence",
        "master_publication_events",
        ["revision_confidence_assessment_id"],
    )
