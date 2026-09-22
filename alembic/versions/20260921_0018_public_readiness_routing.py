"""Version public-readiness routing without changing persisted V1 policy."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260921_0018"
down_revision: str | Sequence[str] | None = "20260915_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_review_routing_policy_version", "review_routing_assessments", type_="check"
    )
    op.create_check_constraint(
        "ck_review_routing_policy_version",
        "review_routing_assessments",
        "policy_version IN ('V1', 'V2')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_review_routing_policy_version", "review_routing_assessments", type_="check"
    )
    op.create_check_constraint(
        "ck_review_routing_policy_version", "review_routing_assessments", "policy_version IN ('V1')"
    )
