"""Add lease-token fencing to the transactional outbox."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0006"
down_revision: str | None = "20260824_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("claim_owner", sa.String(200), nullable=True))
    op.add_column(
        "outbox_events",
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_outbox_events_lease_consistent",
        "outbox_events",
        "(claim_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL) OR "
        "(claim_owner IS NOT NULL AND claim_owner <> '' AND lease_token IS NOT NULL "
        "AND lease_expires_at IS NOT NULL)",
    )
    op.create_index(
        "ix_outbox_events_relay_claim",
        "outbox_events",
        ["status", "event_type", "available_at", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_relay_claim", table_name="outbox_events")
    op.drop_constraint("ck_outbox_events_lease_consistent", "outbox_events", type_="check")
    op.drop_column("outbox_events", "lease_expires_at")
    op.drop_column("outbox_events", "lease_token")
    op.drop_column("outbox_events", "claim_owner")
