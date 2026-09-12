"""Create Human Review cases, items, and immutable decisions.

Revision ID: 20260912_0008
Revises: 20260912_0007
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260912_0008"
down_revision: str | Sequence[str] | None = "20260912_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_revision_id", sa.Uuid(), nullable=False),
        sa.Column("verification_run_id", sa.Uuid(), nullable=False),
        sa.Column("revision_confidence_assessment_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "IN_REVIEW",
                "RESOLVED",
                "CANCELLED",
                name="ck_review_cases_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "NONE",
                "NORMAL",
                "HIGH",
                "CRITICAL",
                name="ck_review_cases_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "policy_version",
            sa.Enum(
                "V1",
                name="ck_review_cases_policy_version",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("revision_score_snapshot", sa.Integer(), nullable=True),
        sa.Column(
            "revision_review_reason_codes_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "component_breakdown_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                "APPROVED",
                "APPROVED_WITH_CORRECTIONS",
                "REJECTED",
                "REVERIFICATION_REQUESTED",
                name="ck_review_cases_outcome",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "revision_score_snapshot IS NULL OR "
            "(revision_score_snapshot >= 0 AND revision_score_snapshot <= 100)",
            name="ck_review_cases_score_snapshot_range",
        ),
        sa.CheckConstraint(
            "(status = 'QUEUED' AND started_at IS NULL AND resolved_at IS NULL "
            "AND outcome IS NULL) OR "
            "(status = 'IN_REVIEW' AND started_at IS NOT NULL "
            "AND resolved_at IS NULL AND outcome IS NULL) OR "
            "(status = 'RESOLVED' AND started_at IS NOT NULL "
            "AND resolved_at IS NOT NULL AND outcome IS NOT NULL) OR "
            "(status = 'CANCELLED' AND resolved_at IS NOT NULL AND outcome IS NULL)",
            name="ck_review_cases_lifecycle",
        ),
        sa.CheckConstraint(
            "(started_at IS NULL OR started_at >= opened_at) AND "
            "(resolved_at IS NULL OR resolved_at >= opened_at)",
            name="ck_review_cases_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_revision_id"],
            ["recruitment_candidate_revisions.id"],
            name="fk_review_cases_candidate_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_confidence_assessment_id"],
            ["revision_confidence_assessments.id"],
            name="fk_review_cases_revision_confidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_run_id"],
            ["verification_runs.id"],
            name="fk_review_cases_verification_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_confidence_assessment_id",
            name="uq_review_cases_revision_confidence",
        ),
    )
    op.create_index(
        "ix_review_cases_candidate_revision_id",
        "review_cases",
        ["candidate_revision_id"],
    )
    op.create_index(
        "ix_review_cases_verification_run_id",
        "review_cases",
        ["verification_run_id"],
    )
    op.create_index("ix_review_cases_status_priority", "review_cases", ["status", "priority"])
    op.create_index("ix_review_cases_queue_order", "review_cases", ["priority", "opened_at"])

    op.create_table(
        "review_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_case_id", sa.Uuid(), nullable=False),
        sa.Column("item_key", sa.String(length=80), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "FIELD",
                "REVISION",
                name="ck_review_items_scope",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("field_confidence_assessment_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_field_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RESOLVED",
                name="ck_review_items_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "NONE",
                "NORMAL",
                "HIGH",
                "CRITICAL",
                name="ck_review_items_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "policy_version",
            sa.Enum(
                "V1",
                name="ck_review_items_policy_version",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("field_path_snapshot", sa.String(length=255), nullable=True),
        sa.Column(
            "candidate_value_type_snapshot",
            sa.Enum(
                "STRING",
                "INTEGER",
                "DECIMAL",
                "BOOLEAN",
                "DATE",
                "DATETIME",
                "JSON",
                "NULL",
                name="ck_review_items_candidate_value_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "candidate_value_snapshot",
            postgresql.JSONB(astext_type=sa.Text(), none_as_null=True),
            nullable=True,
        ),
        sa.Column("confidence_score_snapshot", sa.Integer(), nullable=True),
        sa.Column(
            "review_reason_codes_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "component_breakdown_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "confidence_score_snapshot IS NULL OR "
            "(confidence_score_snapshot >= 0 AND confidence_score_snapshot <= 100)",
            name="ck_review_items_score_snapshot_range",
        ),
        sa.CheckConstraint(
            "(scope = 'FIELD' AND field_confidence_assessment_id IS NOT NULL "
            "AND candidate_field_id IS NOT NULL AND field_path_snapshot IS NOT NULL "
            "AND candidate_value_type_snapshot IS NOT NULL) OR "
            "(scope = 'REVISION' AND field_confidence_assessment_id IS NULL "
            "AND candidate_field_id IS NULL AND field_path_snapshot IS NULL "
            "AND candidate_value_type_snapshot IS NULL "
            "AND candidate_value_snapshot IS NULL)",
            name="ck_review_items_scope_fields",
        ),
        sa.CheckConstraint(
            "(scope = 'REVISION' AND item_key = 'REVISION') OR "
            "(scope = 'FIELD' AND item_key LIKE 'FIELD:%')",
            name="ck_review_items_key_scope",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND resolved_at IS NULL) OR "
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL)",
            name="ck_review_items_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_field_id"],
            ["candidate_fields.id"],
            name="fk_review_items_candidate_field",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["field_confidence_assessment_id"],
            ["field_confidence_assessments.id"],
            name="fk_review_items_field_confidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_case_id"],
            ["review_cases.id"],
            name="fk_review_items_review_case",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_case_id", "item_key", name="uq_review_items_case_key"),
    )
    op.create_index(
        "ix_review_items_field_confidence_assessment_id",
        "review_items",
        ["field_confidence_assessment_id"],
    )
    op.create_index("ix_review_items_candidate_field_id", "review_items", ["candidate_field_id"])

    op.create_table(
        "review_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "APPROVE_AS_IS",
                "CORRECT_AND_APPROVE",
                "REJECT",
                "REQUEST_REVERIFICATION",
                name="ck_review_decisions_decision",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("reviewer_identifier", sa.String(length=255), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "original_value_snapshot",
            postgresql.JSONB(astext_type=sa.Text(), none_as_null=True),
            nullable=True,
        ),
        sa.Column(
            "original_value_type_snapshot",
            sa.Enum(
                "STRING",
                "INTEGER",
                "DECIMAL",
                "BOOLEAN",
                "DATE",
                "DATETIME",
                "JSON",
                "NULL",
                name="ck_review_decisions_original_value_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "corrected_value_type",
            sa.Enum(
                "STRING",
                "INTEGER",
                "DECIMAL",
                "BOOLEAN",
                "DATE",
                "DATETIME",
                "JSON",
                "NULL",
                name="ck_review_decisions_corrected_value_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "corrected_value",
            postgresql.JSONB(astext_type=sa.Text(), none_as_null=True),
            nullable=True,
        ),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(reviewer_identifier)) > 0",
            name="ck_review_decisions_reviewer_nonblank",
        ),
        sa.CheckConstraint(
            "(decision = 'CORRECT_AND_APPROVE' "
            "AND corrected_value_type IS NOT NULL) OR "
            "(decision <> 'CORRECT_AND_APPROVE' "
            "AND corrected_value_type IS NULL AND corrected_value IS NULL)",
            name="ck_review_decisions_corrected_value",
        ),
        sa.CheckConstraint(
            "decision = 'APPROVE_AS_IS' OR "
            "(decision_note IS NOT NULL AND length(trim(decision_note)) > 0)",
            name="ck_review_decisions_required_note",
        ),
        sa.ForeignKeyConstraint(
            ["review_item_id"],
            ["review_items.id"],
            name="fk_review_decisions_review_item",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_item_id", name="uq_review_decisions_review_item"),
    )


def downgrade() -> None:
    op.drop_table("review_decisions")
    op.drop_index("ix_review_items_candidate_field_id", table_name="review_items")
    op.drop_index("ix_review_items_field_confidence_assessment_id", table_name="review_items")
    op.drop_table("review_items")
    op.drop_index("ix_review_cases_queue_order", table_name="review_cases")
    op.drop_index("ix_review_cases_status_priority", table_name="review_cases")
    op.drop_index("ix_review_cases_verification_run_id", table_name="review_cases")
    op.drop_index("ix_review_cases_candidate_revision_id", table_name="review_cases")
    op.drop_table("review_cases")
