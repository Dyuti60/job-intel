"""Create verification runs, field results, and evidence assessments.

Revision ID: 20260912_0006
Revises: 20260912_0005
Create Date: 2026-09-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260912_0006"
down_revision: str | Sequence[str] | None = "20260912_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_revision_id", sa.Uuid(), nullable=False),
        sa.Column(
            "candidate_revision_hash_snapshot", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "COMPLETED",
                "PARTIAL",
                "FAILED",
                name="ck_verification_runs_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "trigger_type",
            sa.Enum(
                "MANUAL",
                "AUTOMATED",
                "RETRY",
                name="ck_verification_runs_trigger_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fields_total", sa.Integer(), nullable=False),
        sa.Column("fields_confirmed", sa.Integer(), nullable=False),
        sa.Column("fields_conflicted", sa.Integer(), nullable=False),
        sa.Column("fields_insufficient", sa.Integer(), nullable=False),
        sa.Column("fields_not_applicable", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "fields_total >= 0 AND fields_confirmed >= 0 "
            "AND fields_conflicted >= 0 AND fields_insufficient >= 0 "
            "AND fields_not_applicable >= 0",
            name="ck_verification_runs_nonnegative_counters",
        ),
        sa.CheckConstraint(
            "fields_confirmed + fields_conflicted + fields_insufficient "
            "+ fields_not_applicable <= fields_total",
            name="ck_verification_runs_counter_total",
        ),
        sa.CheckConstraint(
            "length(candidate_revision_hash_snapshot) = 64 "
            "AND candidate_revision_hash_snapshot = "
            "lower(candidate_revision_hash_snapshot)",
            name="ck_verification_runs_revision_hash_format",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND started_at IS NULL AND completed_at IS NULL) "
            "OR (status = 'RUNNING' AND started_at IS NOT NULL "
            "AND completed_at IS NULL) "
            "OR (status IN ('COMPLETED', 'PARTIAL', 'FAILED') "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_verification_runs_lifecycle_times",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_revision_id"],
            ["recruitment_candidate_revisions.id"],
            name="fk_verification_runs_candidate_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_verification_runs_candidate_revision_id",
        "verification_runs",
        ["candidate_revision_id"],
    )
    op.create_index("ix_verification_runs_status", "verification_runs", ["status"])

    op.create_table(
        "field_verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("verification_run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_field_id", sa.Uuid(), nullable=False),
        sa.Column(
            "candidate_field_path_snapshot", sa.String(length=255), nullable=False
        ),
        sa.Column(
            "candidate_field_value_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "candidate_field_type_snapshot",
            sa.Enum(
                "STRING",
                "INTEGER",
                "DECIMAL",
                "BOOLEAN",
                "DATE",
                "DATETIME",
                "JSON",
                "NULL",
                name="ck_field_verifications_candidate_value_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "FINALIZED",
                name="ck_field_verifications_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                "CONFIRMED",
                "CONFLICT",
                "INSUFFICIENT_EVIDENCE",
                "NOT_APPLICABLE",
                name="ck_field_verifications_outcome",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "reason_code",
            sa.Enum(
                "AUTHORITATIVE_SUPPORT",
                "MULTI_SOURCE_SUPPORT",
                "AUTHORITATIVE_CONFLICT",
                "SOURCE_CONFLICT",
                "NO_EVIDENCE",
                "ONLY_SECONDARY_EVIDENCE",
                "INSUFFICIENT_SUPPORT",
                "MANUALLY_MARKED_NOT_APPLICABLE",
                name="ck_field_verifications_reason",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("finding_summary", sa.Text(), nullable=True),
        sa.Column("authoritative_support_count", sa.Integer(), nullable=False),
        sa.Column("official_support_count", sa.Integer(), nullable=False),
        sa.Column("secondary_support_count", sa.Integer(), nullable=False),
        sa.Column("authoritative_conflict_count", sa.Integer(), nullable=False),
        sa.Column("official_conflict_count", sa.Integer(), nullable=False),
        sa.Column("secondary_conflict_count", sa.Integer(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "authoritative_support_count >= 0 AND official_support_count >= 0 "
            "AND secondary_support_count >= 0 "
            "AND authoritative_conflict_count >= 0 "
            "AND official_conflict_count >= 0 "
            "AND secondary_conflict_count >= 0 AND evidence_count >= 0",
            name="ck_field_verifications_nonnegative_counts",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND outcome IS NULL AND reason_code IS NULL "
            "AND finding_summary IS NULL AND finalized_at IS NULL) "
            "OR (status = 'FINALIZED' AND outcome IS NOT NULL "
            "AND reason_code IS NOT NULL AND finding_summary IS NOT NULL "
            "AND finalized_at IS NOT NULL)",
            name="ck_field_verifications_finalization",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_field_id"],
            ["candidate_fields.id"],
            name="fk_field_verifications_candidate_field",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verification_run_id"],
            ["verification_runs.id"],
            name="fk_field_verifications_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "verification_run_id",
            "candidate_field_id",
            name="uq_field_verifications_run_field",
        ),
    )
    op.create_index(
        "ix_field_verifications_candidate_field_id",
        "field_verifications",
        ["candidate_field_id"],
    )

    op.create_table(
        "verification_evidence_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("field_verification_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column(
            "assessment",
            sa.Enum(
                "SUPPORTS",
                "CONTRADICTS",
                "CONTEXT_ONLY",
                name="ck_verification_assessments_assessment",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "asserted_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "asserted_value_type",
            sa.Enum(
                "STRING",
                "INTEGER",
                "DECIMAL",
                "BOOLEAN",
                "DATE",
                "DATETIME",
                "JSON",
                "NULL",
                name="ck_verification_assessments_asserted_value_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "source_class_snapshot",
            sa.Enum(
                "AUTHORITATIVE_OFFICIAL",
                "OFFICIAL_SUPPORTING",
                "SECONDARY_DISCOVERY_ONLY",
                name="ck_verification_assessments_source_class",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("assessment_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
            name="fk_verification_assessments_evidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["field_verification_id"],
            ["field_verifications.id"],
            name="fk_verification_assessments_field",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "field_verification_id",
            "evidence_id",
            name="uq_verification_assessments_field_evidence",
        ),
    )
    op.create_index(
        "ix_verification_assessments_evidence_id",
        "verification_evidence_assessments",
        ["evidence_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_verification_assessments_evidence_id",
        table_name="verification_evidence_assessments",
    )
    op.drop_table("verification_evidence_assessments")
    op.drop_index(
        "ix_field_verifications_candidate_field_id",
        table_name="field_verifications",
    )
    op.drop_table("field_verifications")
    op.drop_index("ix_verification_runs_status", table_name="verification_runs")
    op.drop_index(
        "ix_verification_runs_candidate_revision_id",
        table_name="verification_runs",
    )
    op.drop_table("verification_runs")
