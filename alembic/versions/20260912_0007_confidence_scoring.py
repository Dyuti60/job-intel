"""Create explainable confidence assessments and review routing metadata.

Revision ID: 20260912_0007
Revises: 20260912_0006
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260912_0007"
down_revision: str | Sequence[str] | None = "20260912_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "field_confidence_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("field_verification_id", sa.Uuid(), nullable=False),
        sa.Column(
            "policy_version",
            sa.Enum(
                "V1",
                name="ck_field_confidence_policy_version",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column(
            "criticality",
            sa.Enum(
                "CRITICAL",
                "STANDARD",
                name="ck_field_confidence_criticality",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column(
            "review_priority",
            sa.Enum(
                "NONE",
                "NORMAL",
                "HIGH",
                "CRITICAL",
                name="ck_field_confidence_review_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "review_reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "component_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_field_confidence_score_range",
        ),
        sa.CheckConstraint(
            "length(input_hash) = 64 AND input_hash = lower(input_hash)",
            name="ck_field_confidence_input_hash_format",
        ),
        sa.ForeignKeyConstraint(
            ["field_verification_id"],
            ["field_verifications.id"],
            name="fk_field_confidence_field_verification",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "field_verification_id",
            "policy_version",
            name="uq_field_confidence_verification_policy",
        ),
    )

    op.create_table(
        "revision_confidence_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("verification_run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_revision_id", sa.Uuid(), nullable=False),
        sa.Column(
            "policy_version",
            sa.Enum(
                "V1",
                name="ck_revision_confidence_policy_version",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("coverage_ratio", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("fields_total", sa.Integer(), nullable=False),
        sa.Column("fields_scored", sa.Integer(), nullable=False),
        sa.Column("fields_not_applicable", sa.Integer(), nullable=False),
        sa.Column("critical_fields_total", sa.Integer(), nullable=False),
        sa.Column("critical_fields_requiring_review", sa.Integer(), nullable=False),
        sa.Column("fields_requiring_review", sa.Integer(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column(
            "review_priority",
            sa.Enum(
                "NONE",
                "NORMAL",
                "HIGH",
                "CRITICAL",
                name="ck_revision_confidence_review_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "review_reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "component_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_revision_confidence_score_range",
        ),
        sa.CheckConstraint(
            "coverage_ratio >= 0 AND coverage_ratio <= 1",
            name="ck_revision_confidence_coverage_range",
        ),
        sa.CheckConstraint(
            "fields_total >= 0 AND fields_scored >= 0 "
            "AND fields_not_applicable >= 0 AND critical_fields_total >= 0 "
            "AND critical_fields_requiring_review >= 0 "
            "AND fields_requiring_review >= 0",
            name="ck_revision_confidence_nonnegative_counts",
        ),
        sa.CheckConstraint(
            "fields_scored + fields_not_applicable <= fields_total "
            "AND fields_requiring_review <= fields_total "
            "AND critical_fields_requiring_review <= critical_fields_total "
            "AND critical_fields_total <= fields_total",
            name="ck_revision_confidence_count_relationships",
        ),
        sa.CheckConstraint(
            "length(input_hash) = 64 AND input_hash = lower(input_hash)",
            name="ck_revision_confidence_input_hash_format",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_revision_id"],
            ["recruitment_candidate_revisions.id"],
            name="fk_revision_confidence_candidate_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_run_id"],
            ["verification_runs.id"],
            name="fk_revision_confidence_verification_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "verification_run_id",
            "policy_version",
            name="uq_revision_confidence_run_policy",
        ),
    )
    op.create_index(
        "ix_revision_confidence_candidate_revision_id",
        "revision_confidence_assessments",
        ["candidate_revision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_revision_confidence_candidate_revision_id",
        table_name="revision_confidence_assessments",
    )
    op.drop_table("revision_confidence_assessments")
    op.drop_table("field_confidence_assessments")
