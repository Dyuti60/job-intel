"""Add routing-driven review linkage and Post-aware Master snapshots.

Revision ID: 20260914_0014
Revises: 20260914_0013
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260914_0014"
down_revision: str | Sequence[str] | None = "20260914_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("review_cases", sa.Column("review_routing_assessment_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_review_cases_review_routing",
        "review_cases",
        "review_routing_assessments",
        ["review_routing_assessment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_review_cases_review_routing",
        "review_cases",
        ["review_routing_assessment_id"],
    )
    op.create_unique_constraint(
        "uq_master_fields_id_revision",
        "master_fields",
        ["id", "master_revision_id"],
    )

    op.create_table(
        "master_posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("master_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_recruitment_post_id", sa.Uuid(), nullable=False),
        sa.Column("post_key", sa.String(length=128), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("normalized_name", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("ordinal >= 1", name="ck_master_posts_positive_ordinal"),
        sa.ForeignKeyConstraint(
            ["master_revision_id"],
            ["recruitment_master_revisions.id"],
            name="fk_master_posts_master_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_recruitment_post_id"],
            ["recruitment_posts.id"],
            name="fk_master_posts_source_post",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "master_revision_id", name="uq_master_posts_id_revision"),
        sa.UniqueConstraint(
            "master_revision_id", "ordinal", name="uq_master_posts_revision_ordinal"
        ),
        sa.UniqueConstraint("master_revision_id", "post_key", name="uq_master_posts_revision_key"),
    )
    op.create_index("ix_master_posts_source_post", "master_posts", ["source_recruitment_post_id"])

    op.create_table(
        "master_post_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("master_post_id", sa.Uuid(), nullable=False),
        sa.Column("master_revision_id", sa.Uuid(), nullable=False),
        sa.Column("master_field_id", sa.Uuid(), nullable=False),
        sa.Column("source_post_fact_id", sa.Uuid(), nullable=False),
        sa.Column("fact_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["master_field_id", "master_revision_id"],
            ["master_fields.id", "master_fields.master_revision_id"],
            name="fk_master_post_facts_field_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["master_post_id", "master_revision_id"],
            ["master_posts.id", "master_posts.master_revision_id"],
            name="fk_master_post_facts_post_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_post_fact_id"],
            ["post_facts.id"],
            name="fk_master_post_facts_source_fact",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("master_field_id", name="uq_master_post_facts_master_field"),
        sa.UniqueConstraint("master_post_id", "fact_key", name="uq_master_post_facts_post_key"),
    )
    op.create_index(
        "ix_master_post_facts_source_fact", "master_post_facts", ["source_post_fact_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_master_post_facts_source_fact", table_name="master_post_facts")
    op.drop_table("master_post_facts")
    op.drop_index("ix_master_posts_source_post", table_name="master_posts")
    op.drop_table("master_posts")
    op.drop_constraint("uq_master_fields_id_revision", "master_fields", type_="unique")
    op.drop_constraint("uq_review_cases_review_routing", "review_cases", type_="unique")
    op.drop_constraint("fk_review_cases_review_routing", "review_cases", type_="foreignkey")
    op.drop_column("review_cases", "review_routing_assessment_id")
