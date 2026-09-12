"""Create operational notification delivery history.

Revision ID: 20260912_0011
Revises: 20260912_0010
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260912_0011"
down_revision: str | None = "20260912_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operational_notification_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("pipeline_run_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=15), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("channel", sa.String(length=4), nullable=False),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column("message", sa.String(length=2000), nullable=False),
        sa.Column("delivery_status", sa.String(length=9), nullable=False),
        sa.Column("delivery_error", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('PIPELINE_FAILED', 'RUNNING_STALE', 'SUCCESS_OVERDUE')",
            name="ck_operational_notifications_event_type",
        ),
        sa.CheckConstraint(
            "severity IN ('WARNING', 'CRITICAL')",
            name="ck_operational_notifications_severity",
        ),
        sa.CheckConstraint(
            "channel IN ('LOG', 'FILE')",
            name="ck_operational_notifications_channel",
        ),
        sa.CheckConstraint(
            "delivery_status IN ('PENDING', 'DELIVERED', 'FAILED')",
            name="ck_operational_notifications_delivery_status",
        ),
        sa.CheckConstraint(
            "length(deduplication_key) = 64 AND "
            "deduplication_key = lower(deduplication_key)",
            name="ck_operational_notifications_dedup_hash",
        ),
        sa.CheckConstraint(
            "length(message) BETWEEN 1 AND 2000",
            name="ck_operational_notifications_message_length",
        ),
        sa.CheckConstraint(
            "delivery_error IS NULL OR length(delivery_error) <= 2000",
            name="ck_operational_notifications_error_length",
        ),
        sa.CheckConstraint(
            "(delivery_status = 'PENDING' AND delivered_at IS NULL "
            "AND delivery_error IS NULL) OR "
            "(delivery_status = 'DELIVERED' AND delivered_at IS NOT NULL "
            "AND delivery_error IS NULL) OR "
            "(delivery_status = 'FAILED' AND delivered_at IS NULL "
            "AND delivery_error IS NOT NULL)",
            name="ck_operational_notifications_delivery_shape",
        ),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deduplication_key"),
    )
    op.create_index(
        "ix_operational_notifications_source_created",
        "operational_notification_events",
        ["source_code", "created_at"],
    )
    op.create_index(
        "ix_operational_notifications_event_type",
        "operational_notification_events",
        ["event_type"],
    )
    op.create_index(
        "ix_operational_notifications_delivery_status",
        "operational_notification_events",
        ["delivery_status"],
    )
    op.create_index(
        "ix_operational_notifications_pipeline_run_id",
        "operational_notification_events",
        ["pipeline_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operational_notifications_pipeline_run_id",
        table_name="operational_notification_events",
    )
    op.drop_index(
        "ix_operational_notifications_delivery_status",
        table_name="operational_notification_events",
    )
    op.drop_index(
        "ix_operational_notifications_event_type",
        table_name="operational_notification_events",
    )
    op.drop_index(
        "ix_operational_notifications_source_created",
        table_name="operational_notification_events",
    )
    op.drop_table("operational_notification_events")
