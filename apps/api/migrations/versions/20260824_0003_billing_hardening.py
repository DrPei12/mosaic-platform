"""Harden wallet money invariants and make the ledger append-only."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0003"
down_revision: str | None = "20260824_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A reservation's currency is persisted rather than inferred only through
    # a mutable join.  Existing rows are backfilled from their wallet before
    # the column becomes NOT NULL.
    op.add_column(
        "balance_reservations",
        sa.Column("currency", sa.String(3), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE balance_reservations AS reservations "
            "SET currency = wallets.currency "
            "FROM wallet_accounts AS wallets "
            "WHERE reservations.wallet_account_id = wallets.id "
            "AND reservations.tenant_id = wallets.tenant_id"
        )
    )
    op.alter_column("balance_reservations", "currency", nullable=False)
    op.add_column(
        "balance_reservations",
        sa.Column("captured_amount_minor", sa.BigInteger(), nullable=True),
    )
    # Preserve idempotent capture semantics for any already-committed rows.
    # A zero-debit committed reservation is a valid free result, so COALESCE
    # deliberately records zero when no debit journal exists.
    op.execute(
        sa.text(
            "UPDATE balance_reservations AS reservations "
            "SET captured_amount_minor = COALESCE(( "
            "SELECT SUM(entries.amount_minor) FROM ledger_entries AS entries "
            "WHERE entries.tenant_id = reservations.tenant_id "
            "AND entries.reservation_id = reservations.id "
            "AND entries.entry_type = 'debit' "
            "), 0) "
            "WHERE reservations.status = 'committed'"
        )
    )

    # 0002 only checked case.  Replace those checks with the full three-letter
    # ISO-style code invariant while keeping their stable constraint names.
    op.drop_constraint("ck_wallet_accounts_currency_upper", "wallet_accounts", type_="check")
    op.drop_constraint("ck_ledger_entries_currency_upper", "ledger_entries", type_="check")
    op.create_check_constraint(
        "ck_wallet_accounts_currency_upper",
        "wallet_accounts",
        "char_length(currency) = 3 AND currency = upper(currency) "
        "AND currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        "ck_wallet_accounts_version_nonnegative",
        "wallet_accounts",
        "version >= 0",
    )
    op.create_check_constraint(
        "ck_balance_reservations_currency_upper",
        "balance_reservations",
        "char_length(currency) = 3 AND currency = upper(currency) "
        "AND currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        "ck_balance_reservations_captured_amount_valid",
        "balance_reservations",
        "captured_amount_minor IS NULL OR "
        "(captured_amount_minor >= 0 AND captured_amount_minor <= amount_minor)",
    )
    op.create_check_constraint(
        "ck_balance_reservations_capture_status_consistent",
        "balance_reservations",
        "(status = 'committed' AND captured_amount_minor IS NOT NULL) OR "
        "(status <> 'committed' AND captured_amount_minor IS NULL)",
    )
    op.create_check_constraint(
        "ck_ledger_entries_currency_upper",
        "ledger_entries",
        "char_length(currency) = 3 AND currency = upper(currency) "
        "AND currency ~ '^[A-Z]{3}$'",
    )

    # Application code only appends journal entries.  This trigger makes that
    # property survive a direct SQL client, an accidental ORM update, or a
    # future maintenance script.  Corrections must be compensating entries.
    op.execute(
        sa.text(
            "CREATE OR REPLACE FUNCTION prevent_ledger_entries_mutation() "
            "RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN "
            "RAISE EXCEPTION USING ERRCODE = '55000', "
            "MESSAGE = 'ledger_entries is append-only'; "
            "END; $$"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_ledger_entries_append_only "
            "BEFORE UPDATE OR DELETE ON ledger_entries "
            "FOR EACH ROW EXECUTE FUNCTION prevent_ledger_entries_mutation()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ledger_entries_append_only ON ledger_entries"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_ledger_entries_mutation()"))
    op.drop_constraint("ck_ledger_entries_currency_upper", "ledger_entries", type_="check")
    op.drop_constraint(
        "ck_balance_reservations_captured_amount_valid",
        "balance_reservations",
        type_="check",
    )
    op.drop_constraint(
        "ck_balance_reservations_capture_status_consistent",
        "balance_reservations",
        type_="check",
    )
    op.drop_constraint(
        "ck_balance_reservations_currency_upper",
        "balance_reservations",
        type_="check",
    )
    op.drop_constraint("ck_wallet_accounts_version_nonnegative", "wallet_accounts", type_="check")
    op.drop_constraint("ck_wallet_accounts_currency_upper", "wallet_accounts", type_="check")
    op.drop_column("balance_reservations", "captured_amount_minor")
    op.drop_column("balance_reservations", "currency")
    op.create_check_constraint(
        "ck_wallet_accounts_currency_upper",
        "wallet_accounts",
        "currency = upper(currency)",
    )
    op.create_check_constraint(
        "ck_ledger_entries_currency_upper",
        "ledger_entries",
        "currency = upper(currency)",
    )
