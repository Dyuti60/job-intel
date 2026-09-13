"""Add immutable advertisement and post domain foundation.

Revision ID: 20260914_0012
Revises: 20260912_0011
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260914_0012"
down_revision: str | Sequence[str] | None = "20260912_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_candidate_fields_id_revision",
        "candidate_fields",
        ["id", "candidate_revision_id"],
    )
    op.create_table(
        "advertisements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruitment_candidate_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["recruitment_candidate_id"], ["recruitment_candidates.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recruitment_candidate_id", name="uq_advertisements_recruitment_candidate"
        ),
    )
    op.create_table(
        "advertisement_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("advertisement_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_revision_id", sa.Uuid(), nullable=False),
        sa.Column(
            "split_status",
            sa.Enum(
                "LEGACY_UNSPLIT",
                "EXPLICIT",
                "AMBIGUOUS",
                name="ck_advertisement_revisions_split_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("detected_post_count", sa.Integer(), nullable=True),
        sa.Column("split_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(split_status = 'EXPLICIT' AND detected_post_count >= 1) OR "
            "(split_status IN ('LEGACY_UNSPLIT', 'AMBIGUOUS') "
            "AND detected_post_count IS NULL)",
            name="ck_advertisement_revisions_split_shape",
        ),
        sa.ForeignKeyConstraint(["advertisement_id"], ["advertisements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["candidate_revision_id"],
            ["recruitment_candidate_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_revision_id", name="uq_advertisement_revisions_candidate_revision"
        ),
        sa.UniqueConstraint(
            "id",
            "candidate_revision_id",
            name="uq_advertisement_revisions_id_candidate_revision",
        ),
    )
    op.create_index(
        "ix_advertisement_revisions_advertisement",
        "advertisement_revisions",
        ["advertisement_id"],
    )
    op.create_table(
        "recruitment_posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("advertisement_revision_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_revision_id", sa.Uuid(), nullable=False),
        sa.Column("post_key", sa.String(length=128), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column("source_locator", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("ordinal >= 1", name="ck_recruitment_posts_positive_ordinal"),
        sa.ForeignKeyConstraint(
            ["advertisement_revision_id", "candidate_revision_id"],
            ["advertisement_revisions.id", "advertisement_revisions.candidate_revision_id"],
            name="fk_recruitment_posts_advertisement_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "advertisement_revision_id", "ordinal", name="uq_recruitment_posts_revision_ordinal"
        ),
        sa.UniqueConstraint(
            "advertisement_revision_id", "post_key", name="uq_recruitment_posts_revision_key"
        ),
        sa.UniqueConstraint(
            "id", "candidate_revision_id", name="uq_recruitment_posts_id_candidate_revision"
        ),
    )
    op.create_index(
        "ix_recruitment_posts_candidate_revision", "recruitment_posts", ["candidate_revision_id"]
    )
    op.create_index(
        "ix_recruitment_posts_normalized_name", "recruitment_posts", ["normalized_name"]
    )
    op.create_table(
        "post_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruitment_post_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_revision_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_field_id", sa.Uuid(), nullable=False),
        sa.Column("fact_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_field_id", "candidate_revision_id"],
            ["candidate_fields.id", "candidate_fields.candidate_revision_id"],
            name="fk_post_facts_candidate_field",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recruitment_post_id", "candidate_revision_id"],
            ["recruitment_posts.id", "recruitment_posts.candidate_revision_id"],
            name="fk_post_facts_recruitment_post",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_field_id", name="uq_post_facts_candidate_field"),
        sa.UniqueConstraint("recruitment_post_id", "fact_key", name="uq_post_facts_post_key"),
    )
    op.create_index(
        "ix_post_facts_candidate_revision", "post_facts", ["candidate_revision_id"]
    )

    # Existing candidates are advertisements, but their historical field sets do not prove a
    # deterministic post split. Backfill only the wrapper and mark every revision explicitly.
    op.execute(
        """
        INSERT INTO advertisements (id, recruitment_candidate_id, created_at)
        SELECT md5('advertisement:' || id::text)::uuid, id, created_at
        FROM recruitment_candidates
        """
    )
    op.execute(
        """
        INSERT INTO advertisement_revisions (
            id, advertisement_id, candidate_revision_id, split_status,
            detected_post_count, split_note, created_at
        )
        SELECT
            md5('advertisement-revision:' || revision.id::text)::uuid,
            md5('advertisement:' || revision.recruitment_candidate_id::text)::uuid,
            revision.id,
            'LEGACY_UNSPLIT',
            NULL,
            'Historical advertisement-level extraction; no deterministic post split fabricated.',
            revision.created_at
        FROM recruitment_candidate_revisions AS revision
        """
    )


def downgrade() -> None:
    op.drop_index("ix_post_facts_candidate_revision", table_name="post_facts")
    op.drop_table("post_facts")
    op.drop_index("ix_recruitment_posts_normalized_name", table_name="recruitment_posts")
    op.drop_index("ix_recruitment_posts_candidate_revision", table_name="recruitment_posts")
    op.drop_table("recruitment_posts")
    op.drop_index(
        "ix_advertisement_revisions_advertisement", table_name="advertisement_revisions"
    )
    op.drop_table("advertisement_revisions")
    op.drop_table("advertisements")
    op.drop_constraint(
        "uq_candidate_fields_id_revision", "candidate_fields", type_="unique"
    )
