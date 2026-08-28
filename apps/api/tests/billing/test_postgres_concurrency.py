"""Real PostgreSQL wallet concurrency verification.

There is intentionally no SQLite fallback: row locks, unique races, and
ledger constraints are part of this billing primitive.  Without the dedicated
database URL the whole module is skipped; with it, migration and the test
fixture are created by this module and the test performs real concurrent SQL.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.billing.errors import INSUFFICIENT_FUNDS, BillingConflict
from app.billing.ports import Money, ReservationResult
from app.billing.service import SqlAlchemyBillingService
from app.infrastructure.models import (
    BalanceReservations,
    LedgerEntries,
    Tenants,
    WalletAccounts,
)

_RAW_DATABASE_URL = os.environ.get("BILLING_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _RAW_DATABASE_URL,
    reason="BILLING_TEST_DATABASE_URL is required for real PostgreSQL concurrency tests",
)


def _async_database_url() -> str:
    assert _RAW_DATABASE_URL is not None
    if _RAW_DATABASE_URL.startswith("postgresql+asyncpg://"):
        return _RAW_DATABASE_URL
    if _RAW_DATABASE_URL.startswith("postgresql://"):
        return _RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    raise ValueError("BILLING_TEST_DATABASE_URL must use PostgreSQL")


def _upgrade_schema() -> None:
    database_url = _async_database_url()
    from app.core.settings import settings

    previous_url = settings.database_url
    settings.database_url = database_url
    try:
        root = Path(__file__).parents[2]
        config = Config(str(root / "alembic.ini"))
        command.upgrade(config, "head")
    finally:
        settings.database_url = previous_url


@pytest.mark.asyncio
async def test_concurrent_holds_are_wallet_safe_and_same_source_idempotent() -> None:
    await asyncio.to_thread(_upgrade_schema)
    engine = create_async_engine(_async_database_url(), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    tenant_id = uuid4()
    wallet_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    try:
        async with sessions() as session, session.begin():
            session.add(
                Tenants(
                    id=tenant_id,
                    slug=f"billing-concurrency-{tenant_id.hex[:12]}",
                    name="Billing concurrency test",
                    status="active",
                    settings={},
                )
            )
            session.add(
                WalletAccounts(
                    id=wallet_id,
                    tenant_id=tenant_id,
                    currency="CNY",
                    balance_minor=1_000,
                    reserved_minor=0,
                    version=0,
                    status="active",
                )
            )

        async def hold(source_id: UUID, amount_minor: int) -> ReservationResult:
            async with sessions() as session:
                return await SqlAlchemyBillingService(session).reserve(
                    tenant_id=tenant_id,
                    source_type="concurrency",
                    source_id=source_id,
                    amount=Money(amount_minor, "CNY"),
                    expires_at=expires_at,
                )

        different_sources = await asyncio.gather(
            hold(uuid4(), 600),
            hold(uuid4(), 600),
            return_exceptions=True,
        )
        successes = [item for item in different_sources if isinstance(item, ReservationResult)]
        failures = [item for item in different_sources if isinstance(item, BillingConflict)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert failures[0].code == INSUFFICIENT_FUNDS

        same_source = uuid4()
        duplicate_results = await asyncio.gather(
            hold(same_source, 100),
            hold(same_source, 100),
        )
        assert duplicate_results[0].reservation_id == duplicate_results[1].reservation_id

        async with sessions() as session:
            service = SqlAlchemyBillingService(session)
            first_capture = await service.capture(
                tenant_id=tenant_id,
                reservation_id=duplicate_results[0].reservation_id,
                actual=Money(40, "CNY"),
            )
        async with sessions() as session:
            second_capture = await SqlAlchemyBillingService(session).capture(
                tenant_id=tenant_id,
                reservation_id=duplicate_results[0].reservation_id,
                actual=Money(40, "CNY"),
            )

        assert first_capture.idempotent is False
        assert second_capture.idempotent is True
        assert first_capture.charged.amount_minor == 40
        assert second_capture.charged.amount_minor == 40

        async with sessions() as session:
            wallet = (
                await session.execute(
                    select(WalletAccounts).where(
                        WalletAccounts.tenant_id == tenant_id,
                        WalletAccounts.id == wallet_id,
                    )
                )
            ).scalar_one()
            reservations = (
                await session.execute(
                    select(BalanceReservations).where(
                        BalanceReservations.tenant_id == tenant_id,
                    )
                )
            ).scalars().all()
            ledger_rows = (
                await session.execute(
                    select(LedgerEntries).where(LedgerEntries.tenant_id == tenant_id)
                )
            ).scalars().all()
        assert wallet.balance_minor == 960
        assert wallet.reserved_minor == 600
        assert len(reservations) == 2
        assert len([row for row in ledger_rows if row.entry_type == "hold"]) == 2
        assert len([row for row in ledger_rows if row.entry_type == "debit"]) == 1
    finally:
        # Financial history is append-only even in the concurrency gate.  The
        # UUID-scoped fixture remains in the dedicated test database instead
        # of weakening the ledger trigger solely for cleanup.
        await engine.dispose()
