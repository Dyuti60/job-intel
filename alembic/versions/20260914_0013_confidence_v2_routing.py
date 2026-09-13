"""Add Confidence V2 and independent review-routing assessments.

Revision ID: 20260914_0013
Revises: 20260914_0012
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260914_0013"
down_revision: str | Sequence[str] | None = "20260914_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_policy_constraint(table: str, name: str, values: tuple[str, ...]) -> None:
    op.drop_constraint(name, table, type_="check")
    allowed = ", ".join(f"'{value}'" for value in values)
    op.create_check_constraint(name, table, f"policy_version IN ({allowed})")


def upgrade() -> None:
    for table, name in (
        ("field_confidence_assessments", "ck_field_confidence_policy_version"),
        ("revision_confidence_assessments", "ck_revision_confidence_policy_version"),
        ("review_cases", "ck_review_cases_policy_version"),
        ("review_items", "ck_review_items_policy_version"),
    ):
        _replace_policy_constraint(table, name, ("V1", "V2"))

    op.create_table(
        "review_routing_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision_confidence_assessment_id", sa.Uuid(), nullable=False),
        sa.Column("verification_run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_revision_id", sa.Uuid(), nullable=False),
        sa.Column(
            "policy_version",
            sa.Enum(
                "V1",
                name="ck_review_routing_policy_version",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column(
            "priority",
            sa.Enum(
                "NONE",
                "NORMAL",
                "HIGH",
                "CRITICAL",
                name="ck_review_routing_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("field_routes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("component_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(input_hash) = 64 AND input_hash = lower(input_hash)",
            name="ck_review_routing_input_hash_format",
        ),
        sa.CheckConstraint(
            "(review_required AND priority <> 'NONE') OR "
            "(NOT review_required AND priority = 'NONE')",
            name="ck_review_routing_required_priority",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_revision_id"],
            ["recruitment_candidate_revisions.id"],
            name="fk_review_routing_candidate_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_confidence_assessment_id"],
            ["revision_confidence_assessments.id"],
            name="fk_review_routing_revision_confidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_run_id"],
            ["verification_runs.id"],
            name="fk_review_routing_verification_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_confidence_assessment_id",
            "policy_version",
            name="uq_review_routing_confidence_policy",
        ),
    )
    op.create_index(
        "ix_review_routing_candidate_revision",
        "review_routing_assessments",
        ["candidate_revision_id"],
    )
    op.create_index(
        "ix_review_routing_verification_run",
        "review_routing_assessments",
        ["verification_run_id"],
    )
    op.create_index(
        "ix_review_routing_queue",
        "review_routing_assessments",
        ["review_required", "priority"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_routing_queue", table_name="review_routing_assessments")
    op.drop_index("ix_review_routing_verification_run", table_name="review_routing_assessments")
    op.drop_index("ix_review_routing_candidate_revision", table_name="review_routing_assessments")
    op.drop_table("review_routing_assessments")
    # V2 is additive derived history. Remove only V2 rows so the restored V1-only
    # constraints can be installed; every pre-existing V1 assessment remains untouched.
    op.execute("DELETE FROM revision_confidence_assessments WHERE policy_version = 'V2'")
    op.execute("DELETE FROM field_confidence_assessments WHERE policy_version = 'V2'")
    for table, name in (
        ("review_items", "ck_review_items_policy_version"),
        ("review_cases", "ck_review_cases_policy_version"),
        ("revision_confidence_assessments", "ck_revision_confidence_policy_version"),
        ("field_confidence_assessments", "ck_field_confidence_policy_version"),
    ):
        _replace_policy_constraint(table, name, ("V1",))
