"""Add fenced generation recovery and idempotent provider inbox facts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0011"
down_revision: str | None = "20260826_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("claim_owner", sa.String(200)))
    op.add_column(
        "generation_jobs",
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "generation_jobs",
        sa.Column(
            "reconciliation_status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'not_required'"),
        ),
    )
    op.add_column("generation_jobs", sa.Column("provider_observed_status", sa.String(64)))
    op.add_column(
        "generation_jobs",
        sa.Column("provider_observed_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        sa.text(
            "UPDATE generation_jobs SET status = 'accepted', updated_at = CURRENT_TIMESTAMP "
            "WHERE status IN ('reserved', 'queued')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE generation_jobs SET status = 'submitted_unknown', "
            "reconciliation_status = 'pending', "
            "error_code = 'GENERATION_RECONCILIATION_REQUIRED', "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE status IN ('submitted', 'running', 'storing', 'submitted_unknown')"
        )
    )
    op.create_check_constraint(
        "ck_generation_jobs_fencing_nonnegative",
        "generation_jobs",
        "fencing_token >= 0",
    )
    op.create_check_constraint(
        "ck_generation_jobs_lease_consistent",
        "generation_jobs",
        "(claim_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL) OR "
        "(claim_owner IS NOT NULL AND claim_owner <> '' AND lease_token IS NOT NULL "
        "AND lease_expires_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_generation_jobs_reconciliation_status_values",
        "generation_jobs",
        "reconciliation_status IN ('not_required', 'pending', 'resolved', 'disputed')",
    )
    op.create_index(
        "ix_generation_jobs_recovery_claim",
        "generation_jobs",
        ["status", "reconciliation_status", "lease_expires_at", "updated_at"],
    )

    op.create_table(
        "inbox_events",
        sa.Column("provider_name", sa.String(64), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="received"),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('received', 'processed', 'rejected')",
            name="ck_inbox_events_status_values",
        ),
        sa.CheckConstraint(
            "payload_digest ~ '^[0-9a-f]{64}$'",
            name="ck_inbox_events_payload_digest_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_inbox_events_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inbox_events_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "provider_name",
            "event_key",
            name="uq_inbox_events_provider_event",
        ),
    )
    op.create_index(
        "ix_inbox_events_tenant_status_created",
        "inbox_events",
        ["tenant_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("inbox_events")
    op.drop_index("ix_generation_jobs_recovery_claim", table_name="generation_jobs")
    op.drop_constraint(
        "ck_generation_jobs_reconciliation_status_values",
        "generation_jobs",
        type_="check",
    )
    op.drop_constraint("ck_generation_jobs_lease_consistent", "generation_jobs", type_="check")
    op.drop_constraint(
        "ck_generation_jobs_fencing_nonnegative",
        "generation_jobs",
        type_="check",
    )
    op.drop_column("generation_jobs", "provider_observed_at")
    op.drop_column("generation_jobs", "provider_observed_status")
    op.drop_column("generation_jobs", "reconciliation_status")
    op.drop_column("generation_jobs", "fencing_token")
    op.drop_column("generation_jobs", "lease_expires_at")
    op.drop_column("generation_jobs", "lease_token")
    op.drop_column("generation_jobs", "claim_owner")
