"""Add soft-delete visibility state for generation jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0013"
down_revision: str | None = "20260826_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_generation_jobs_tenant_actor_visible",
        "generation_jobs",
        ["tenant_id", "actor_user_id", "deleted_at", "created_at"],
    )
    op.drop_constraint(
        "ck_generation_artifacts_status_values",
        "generation_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_generation_artifacts_status_values",
        "generation_artifacts",
        "status IN ('pending', 'ready', 'expired', 'delete_pending', 'deleted')",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE generation_artifacts SET status = 'expired' "
            "WHERE status = 'delete_pending'"
        )
    )
    op.drop_constraint(
        "ck_generation_artifacts_status_values",
        "generation_artifacts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_generation_artifacts_status_values",
        "generation_artifacts",
        "status IN ('pending', 'ready', 'expired', 'deleted')",
    )
    op.drop_index("ix_generation_jobs_tenant_actor_visible", table_name="generation_jobs")
    op.drop_column("generation_jobs", "deleted_at")
