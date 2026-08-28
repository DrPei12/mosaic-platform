from uuid import uuid4

from sqlalchemy import CheckConstraint
from sqlalchemy.dialects import postgresql

from app.billing.queries import (
    reservation_by_id_for_update,
    reservation_by_source,
    wallet_by_currency_for_update,
)
from app.infrastructure.models import Base


def test_wallet_and_source_statements_are_tenant_scoped_and_locked() -> None:
    tenant_id = uuid4()
    source_id = uuid4()
    wallet_sql = str(
        wallet_by_currency_for_update(tenant_id, "CNY").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    source_sql = str(
        reservation_by_source(
            tenant_id, "generation_job", source_id, for_update=True
        ).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "FOR UPDATE" in wallet_sql
    assert "FOR UPDATE" in source_sql
    assert str(tenant_id) in wallet_sql
    assert str(source_id) in source_sql


def test_reservation_lock_statement_does_not_use_sqlite_dialect_assumptions() -> None:
    sql = str(
        reservation_by_id_for_update(uuid4(), uuid4()).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "balance_reservations." in sql
    assert "FOR UPDATE" in sql


def test_billing_metadata_has_money_and_capture_invariants() -> None:
    wallets = Base.metadata.tables["wallet_accounts"]
    reservations = Base.metadata.tables["balance_reservations"]
    ledger = Base.metadata.tables["ledger_entries"]

    assert wallets.c.balance_minor.type.python_type is int
    assert wallets.c.reserved_minor.type.python_type is int
    assert reservations.c.amount_minor.type.python_type is int
    assert reservations.c.currency.nullable is False
    assert reservations.c.captured_amount_minor.nullable is True
    assert any(
        isinstance(item, CheckConstraint)
        and item.name == "ck_balance_reservations_captured_amount_valid"
        for item in reservations.constraints
    )
    assert any(
        isinstance(item, CheckConstraint)
        and item.name == "ck_balance_reservations_capture_status_consistent"
        for item in reservations.constraints
    )
    assert any(
        isinstance(item, CheckConstraint)
        and item.name == "ck_ledger_entries_amount_positive"
        for item in ledger.constraints
    )
