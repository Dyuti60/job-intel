"""Add stable public identities to immutable Master Post snapshots.

Revision ID: 20260914_0015
Revises: 20260914_0014
Create Date: 2026-09-14
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260914_0015"
down_revision: str | Sequence[str] | None = "20260914_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("master_posts", sa.Column("public_id", sa.Uuid(), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT mp.id, mr.recruitment_master_id, mp.post_key "
            "FROM master_posts mp "
            "JOIN recruitment_master_revisions mr ON mr.id = mp.master_revision_id"
        )
    )
    for post_id, master_id, post_key in rows:
        public_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"assam-job-intelligence:master-post:{master_id}:{post_key}",
        )
        connection.execute(
            sa.text("UPDATE master_posts SET public_id = :public_id WHERE id = :post_id"),
            {"public_id": public_id, "post_id": post_id},
        )
    op.alter_column("master_posts", "public_id", nullable=False)
    op.create_unique_constraint(
        "uq_master_posts_revision_public_id",
        "master_posts",
        ["master_revision_id", "public_id"],
    )
    op.create_index("ix_master_posts_public_id", "master_posts", ["public_id"])


def downgrade() -> None:
    op.drop_index("ix_master_posts_public_id", table_name="master_posts")
    op.drop_constraint("uq_master_posts_revision_public_id", "master_posts", type_="unique")
    op.drop_column("master_posts", "public_id")
