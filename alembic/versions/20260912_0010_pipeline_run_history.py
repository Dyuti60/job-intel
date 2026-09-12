"""Create persistent pipeline operational run history.

Revision ID: 20260912_0010
Revises: 20260912_0009
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260912_0010"
down_revision: str | None = "20260912_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("authority_code", sa.String(length=64), nullable=False),
        sa.Column("trigger_type", sa.String(length=13), nullable=False),
        sa.Column("status", sa.String(length=7), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("discovery_status", sa.String(length=7), nullable=True),
        sa.Column("verification_status", sa.String(length=7), nullable=True),
        sa.Column("publisher_status", sa.String(length=7), nullable=True),
        sa.Column("review_cases_queued", sa.Integer(), nullable=False),
        sa.Column("masters_created", sa.Integer(), nullable=False),
        sa.Column("masters_updated", sa.Integer(), nullable=False),
        sa.Column("masters_unchanged", sa.Integer(), nullable=False),
        sa.Column("error_stage", sa.String(length=16), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "trigger_type IN ('MANUAL', 'CLI', 'GITHUB_ACTION', 'SCHEDULED')",
            name="ck_pipeline_runs_trigger_type",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED')",
            name="ck_pipeline_runs_status",
        ),
        sa.CheckConstraint(
            "discovery_status IS NULL OR discovery_status IN ('SUCCESS', 'PARTIAL', 'FAILED')",
            name="ck_pipeline_runs_discovery_status",
        ),
        sa.CheckConstraint(
            "verification_status IS NULL OR verification_status IN "
            "('SUCCESS', 'PARTIAL', 'FAILED')",
            name="ck_pipeline_runs_verification_status",
        ),
        sa.CheckConstraint(
            "publisher_status IS NULL OR publisher_status IN ('SUCCESS', 'PARTIAL', 'FAILED')",
            name="ck_pipeline_runs_publisher_status",
        ),
        sa.CheckConstraint(
            "error_stage IS NULL OR error_stage IN "
            "('DISCOVERY', 'VERIFICATION', 'MASTER_PUBLISHER')",
            name="ck_pipeline_runs_error_stage",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_pipeline_runs_duration"
        ),
        sa.CheckConstraint("review_cases_queued >= 0", name="ck_pipeline_runs_review_count"),
        sa.CheckConstraint(
            "masters_created >= 0 AND masters_updated >= 0 AND masters_unchanged >= 0",
            name="ck_pipeline_runs_master_counts",
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND completed_at IS NULL AND duration_ms IS NULL) OR "
            "(status IN ('SUCCESS', 'PARTIAL', 'FAILED') AND completed_at IS NOT NULL "
            "AND duration_ms IS NOT NULL)",
            name="ck_pipeline_runs_completion_shape",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_runs_source_started", "pipeline_runs", ["source_code", "started_at"]
    )
    op.create_index("ix_pipeline_runs_status_started", "pipeline_runs", ["status", "started_at"])
    op.create_index("ix_pipeline_runs_trigger_type", "pipeline_runs", ["trigger_type"])

    op.create_table(
        "pipeline_stage_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_run_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=7), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stage IN ('DISCOVERY', 'VERIFICATION', 'MASTER_PUBLISHER')",
            name="ck_pipeline_stage_runs_stage",
        ),
        sa.CheckConstraint(
            "status IN ('SUCCESS', 'PARTIAL', 'FAILED')",
            name="ck_pipeline_stage_runs_status",
        ),
        sa.CheckConstraint("duration_ms >= 0", name="ck_pipeline_stage_runs_duration"),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pipeline_run_id", "stage", name="uq_pipeline_stage_runs_run_stage"),
    )
    op.create_index("ix_pipeline_stage_runs_status", "pipeline_stage_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_stage_runs_status", table_name="pipeline_stage_runs")
    op.drop_table("pipeline_stage_runs")
    op.drop_index("ix_pipeline_runs_trigger_type", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_status_started", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_source_started", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
