"""Add invited-account credential lifecycle state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0010"
down_revision: str | None = "20260826_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "password_change_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("credential_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("credential_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_credential_lifecycle",
        "users",
        "(password_change_required = false AND credential_expires_at IS NULL "
        "AND credential_used_at IS NULL) OR "
        "(password_change_required = true AND credential_expires_at IS NOT NULL)",
    )
    op.create_index(
        "ix_users_pending_credential",
        "users",
        ["password_change_required", "credential_expires_at"],
    )
    # Existing accounts were created with a normal password and remain
    # unrestricted. New invited accounts are created by the operator CLI.
    op.alter_column("users", "password_change_required", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_users_pending_credential", table_name="users")
    op.drop_constraint("ck_users_credential_lifecycle", "users", type_="check")
    op.drop_column("users", "credential_used_at")
    op.drop_column("users", "credential_expires_at")
    op.drop_column("users", "password_change_required")
