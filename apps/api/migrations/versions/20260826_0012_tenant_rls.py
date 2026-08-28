"""Enable tenant row-level security for user and billing data."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260826_0012"
down_revision: str | None = "20260826_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "tenant_model_entitlements",
    "conversations",
    "messages",
    "inference_requests",
    "chat_stream_events",
    "generation_jobs",
    "generation_artifacts",
    "usage_records",
    "wallet_accounts",
    "balance_reservations",
    "ledger_entries",
    "idempotency_records",
    "outbox_events",
    "inbox_events",
    "audit_events",
)


def upgrade() -> None:
    op.execute(
        "CREATE FUNCTION mosaic_current_tenant_id() RETURNS uuid "
        "LANGUAGE sql STABLE PARALLEL SAFE AS $$ "
        "SELECT NULLIF(current_setting('mosaic.tenant_id', true), '')::uuid $$"
    )
    for table_name in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table_name}_tenant_isolation" ON "{table_name}" '
            "USING (tenant_id = mosaic_current_tenant_id()) "
            "WITH CHECK (tenant_id = mosaic_current_tenant_id())"
        )


def downgrade() -> None:
    for table_name in reversed(TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS "{table_name}_tenant_isolation" ON "{table_name}"')
        op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')
    op.execute("DROP FUNCTION IF EXISTS mosaic_current_tenant_id()")
