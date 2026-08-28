"""Prevent one Provider request or task from being attached twice."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0004"
down_revision: str | None = "20260824_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("inference_requests", "generation_jobs"):
        op.create_index(
            f"uq_{table}_provider_request",
            table,
            ["tenant_id", "model_deployment_id", "provider_request_id"],
            unique=True,
            postgresql_where=sa.text("provider_request_id IS NOT NULL"),
        )
        op.create_index(
            f"uq_{table}_provider_task",
            table,
            ["tenant_id", "model_deployment_id", "provider_task_id"],
            unique=True,
            postgresql_where=sa.text("provider_task_id IS NOT NULL"),
        )


def downgrade() -> None:
    for table in ("generation_jobs", "inference_requests"):
        op.drop_index(f"uq_{table}_provider_task", table_name=table)
        op.drop_index(f"uq_{table}_provider_request", table_name=table)
