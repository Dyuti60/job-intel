"""Create discovery runs, source documents, and observations.

Revision ID: 20260912_0003
Revises: 20260912_0002
Create Date: 2026-09-12
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260912_0003"
down_revision: str | Sequence[str] | None = "20260912_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_endpoint_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "SUCCEEDED",
                "PARTIAL",
                "FAILED",
                name="ck_discovery_runs_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "trigger_type",
            sa.Enum(
                "MANUAL",
                "SCHEDULED",
                "RETRY",
                name="ck_discovery_runs_trigger_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("documents_discovered", sa.Integer(), nullable=False),
        sa.Column("documents_new", sa.Integer(), nullable=False),
        sa.Column("documents_changed", sa.Integer(), nullable=False),
        sa.Column("documents_unchanged", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "documents_discovered >= 0 AND documents_new >= 0 "
            "AND documents_changed >= 0 AND documents_unchanged >= 0",
            name="ck_discovery_runs_nonnegative_counters",
        ),
        sa.CheckConstraint(
            "(status IN ('PENDING', 'RUNNING') AND completed_at IS NULL) "
            "OR (status IN ('SUCCEEDED', 'PARTIAL', 'FAILED') AND completed_at IS NOT NULL)",
            name="ck_discovery_runs_completion_time",
        ),
        sa.ForeignKeyConstraint(
            ["source_endpoint_id"],
            ["source_endpoints.id"],
            name="fk_discovery_runs_source_endpoint",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discovery_runs_source_endpoint_id",
        "discovery_runs",
        ["source_endpoint_id"],
    )
    op.create_index("ix_discovery_runs_started_at", "discovery_runs", ["started_at"])
    op.create_index("ix_discovery_runs_status", "discovery_runs", ["status"])

    op.create_table(
        "source_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("first_discovery_run_id", sa.Uuid(), nullable=False),
        sa.Column("latest_discovery_run_id", sa.Uuid(), nullable=False),
        sa.Column("document_url", sa.String(length=2048), nullable=False),
        sa.Column("normalized_document_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "document_type",
            sa.Enum(
                "HTML",
                "PDF",
                "JSON",
                "OTHER",
                name="ck_source_documents_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=True),
        sa.Column("http_etag", sa.String(length=512), nullable=True),
        sa.Column("http_last_modified", sa.String(length=255), nullable=True),
        sa.Column("storage_uri", sa.String(length=2048), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "UNAVAILABLE",
                "FAILED",
                name="ck_source_documents_status",
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
        sa.CheckConstraint(
            "content_length IS NULL OR content_length >= 0",
            name="ck_source_documents_nonnegative_length",
        ),
        sa.ForeignKeyConstraint(
            ["first_discovery_run_id"],
            ["discovery_runs.id"],
            name="fk_source_documents_first_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["latest_discovery_run_id"],
            ["discovery_runs.id"],
            name="fk_source_documents_latest_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_endpoint_id"],
            ["source_endpoints.id"],
            name="fk_source_documents_source_endpoint",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_endpoint_id",
            "normalized_document_url",
            "content_hash",
            name="uq_source_documents_version_identity",
        ),
    )
    op.create_index(
        "ix_source_documents_content_hash",
        "source_documents",
        ["content_hash"],
    )
    op.create_index(
        "ix_source_documents_document_type",
        "source_documents",
        ["document_type"],
    )
    op.create_index(
        "ix_source_documents_normalized_url",
        "source_documents",
        ["normalized_document_url"],
    )
    op.create_index("ix_source_documents_status", "source_documents", ["status"])

    op.create_table(
        "discovery_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("discovery_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "observation_status",
            sa.Enum(
                "NEW",
                "UNCHANGED",
                "CHANGED",
                "UNAVAILABLE",
                name="ck_discovery_observations_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("observed_url", sa.String(length=2048), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("content_length", sa.Integer(), nullable=True),
        sa.Column("http_etag", sa.String(length=512), nullable=True),
        sa.Column("http_last_modified", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_length IS NULL OR content_length >= 0",
            name="ck_discovery_observations_nonnegative_length",
        ),
        sa.CheckConstraint(
            "http_status_code IS NULL OR "
            "(http_status_code >= 100 AND http_status_code <= 599)",
            name="ck_discovery_observations_http_status",
        ),
        sa.ForeignKeyConstraint(
            ["discovery_run_id"],
            ["discovery_runs.id"],
            name="fk_discovery_observations_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            name="fk_discovery_observations_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "discovery_run_id",
            "source_document_id",
            name="uq_discovery_observations_run_document",
        ),
    )
    op.create_index(
        "ix_discovery_observations_document_id",
        "discovery_observations",
        ["source_document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discovery_observations_document_id",
        table_name="discovery_observations",
    )
    op.drop_table("discovery_observations")
    op.drop_index("ix_source_documents_status", table_name="source_documents")
    op.drop_index("ix_source_documents_normalized_url", table_name="source_documents")
    op.drop_index("ix_source_documents_document_type", table_name="source_documents")
    op.drop_index("ix_source_documents_content_hash", table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_index("ix_discovery_runs_status", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_started_at", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_source_endpoint_id", table_name="discovery_runs")
    op.drop_table("discovery_runs")
