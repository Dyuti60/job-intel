"""Create the Assam Source Registry.

Revision ID: 20260912_0002
Revises: 20260912_0001
Create Date: 2026-09-12
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260912_0002"
down_revision: str | Sequence[str] | None = "20260912_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recruiting_authorities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "authority_type",
            sa.Enum(
                "COMMISSION",
                "DEPARTMENT",
                "BOARD",
                "POLICE",
                "AUTONOMOUS_BODY",
                "PSU",
                "UNIVERSITY",
                "OTHER",
                name="ck_recruiting_authorities_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("official_website_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "INACTIVE",
                name="ck_recruiting_authorities_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_recruiting_authorities_code"),
    )
    op.create_table(
        "source_endpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recruiting_authority_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum(
                "RECRUITMENT_INDEX",
                "NOTIFICATION_INDEX",
                "APPLICATION_PORTAL",
                "DOCUMENT_LISTING",
                "OTHER",
                name="ck_source_endpoints_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "source_class",
            sa.Enum(
                "AUTHORITATIVE_OFFICIAL",
                "OFFICIAL_SUPPORTING",
                "SECONDARY_DISCOVERY_ONLY",
                name="ck_source_endpoints_class",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "INACTIVE",
                "DISABLED",
                name="ck_source_endpoints_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("discovery_enabled", sa.Boolean(), nullable=False),
        sa.Column("adapter_key", sa.String(length=128), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provenance_note", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["recruiting_authority_id"],
            ["recruiting_authorities.id"],
            name="fk_source_endpoints_recruiting_authority",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_url", name="uq_source_endpoints_canonical_url"),
    )
    op.create_index(
        "ix_source_endpoints_authority_id",
        "source_endpoints",
        ["recruiting_authority_id"],
    )
    op.create_index(
        "ix_source_endpoints_discovery",
        "source_endpoints",
        ["status", "discovery_enabled"],
    )
    op.create_index(
        "ix_source_endpoints_source_class",
        "source_endpoints",
        ["source_class"],
    )
    op.create_index(
        "ix_source_endpoints_source_type",
        "source_endpoints",
        ["source_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_endpoints_source_type", table_name="source_endpoints")
    op.drop_index("ix_source_endpoints_source_class", table_name="source_endpoints")
    op.drop_index("ix_source_endpoints_discovery", table_name="source_endpoints")
    op.drop_index("ix_source_endpoints_authority_id", table_name="source_endpoints")
    op.drop_table("source_endpoints")
    op.drop_table("recruiting_authorities")
