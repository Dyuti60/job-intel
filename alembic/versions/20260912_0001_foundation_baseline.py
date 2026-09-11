"""Create the T-001 schema baseline.

Revision ID: 20260912_0001
Revises:
Create Date: 2026-09-12
"""
from collections.abc import Sequence

revision: str = "20260912_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Establish an empty baseline; domain tables begin in T-002."""


def downgrade() -> None:
    """Remove the empty baseline."""
