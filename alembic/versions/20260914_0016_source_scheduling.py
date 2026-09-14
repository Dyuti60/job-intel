"""Add deterministic source scheduling metadata.

Revision ID: 20260914_0016
Revises: 20260914_0015
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260914_0016"
down_revision: str | Sequence[str] | None = "20260914_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_endpoints",
        sa.Column(
            "schedule_group",
            sa.Enum(
                "HIGH_PRIORITY",
                "NORMAL",
                "LOW_FREQUENCY",
                "DISTRICT",
                name="ck_source_endpoints_schedule_group",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default="NORMAL",
        ),
    )
    op.add_column(
        "source_endpoints",
        sa.Column("poll_interval_minutes", sa.Integer(), nullable=False, server_default="1440"),
    )
    op.add_column(
        "source_endpoints",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "source_endpoints",
        sa.Column("requests_per_minute", sa.Integer(), nullable=False, server_default="6"),
    )
    op.add_column("source_endpoints", sa.Column("last_attempted_at", sa.DateTime(timezone=True)))
    op.add_column("source_endpoints", sa.Column("last_successful_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_source_poll_interval", "source_endpoints", "poll_interval_minutes >= 15"
    )
    op.create_check_constraint(
        "ck_source_priority", "source_endpoints", "priority BETWEEN 1 AND 1000"
    )
    op.create_check_constraint(
        "ck_source_rate_limit", "source_endpoints", "requests_per_minute BETWEEN 1 AND 60"
    )
    op.create_index(
        "ix_source_endpoints_schedule",
        "source_endpoints",
        ["status", "discovery_enabled", "schedule_group", "priority"],
    )
    connection = op.get_bind()
    schedules = {
        "apsc_recruitment": ("HIGH_PRIORITY", 360, 10, 6),
        "official_archive_slprb": ("HIGH_PRIORITY", 360, 20, 6),
        "official_archive_dee": ("HIGH_PRIORITY", 720, 30, 6),
        "official_archive_dme": ("NORMAL", 1440, 40, 6),
    }
    for adapter_key, values in schedules.items():
        connection.execute(
            sa.text(
                "UPDATE source_endpoints SET schedule_group=:schedule_group, "
                "poll_interval_minutes=:poll_interval_minutes, priority=:priority, "
                "requests_per_minute=:requests_per_minute WHERE adapter_key=:adapter_key"
            ),
            {
                "adapter_key": adapter_key,
                "schedule_group": values[0],
                "poll_interval_minutes": values[1],
                "priority": values[2],
                "requests_per_minute": values[3],
            },
        )


def downgrade() -> None:
    op.drop_index("ix_source_endpoints_schedule", table_name="source_endpoints")
    op.drop_constraint("ck_source_rate_limit", "source_endpoints", type_="check")
    op.drop_constraint("ck_source_priority", "source_endpoints", type_="check")
    op.drop_constraint("ck_source_poll_interval", "source_endpoints", type_="check")
    for name in (
        "last_successful_at",
        "last_attempted_at",
        "requests_per_minute",
        "priority",
        "poll_interval_minutes",
        "schedule_group",
    ):
        op.drop_column("source_endpoints", name)
