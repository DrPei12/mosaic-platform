"""Idempotently credit a local demo tenant through the immutable ledger."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import settings
from app.infrastructure.database import dispose_engine, session_factory
from app.infrastructure.models import LedgerEntries, Tenants, WalletAccounts


async def _run(*, tenant_slug: str, amount_minor: int) -> None:
    if settings.app_environment == "production":
        raise RuntimeError("demo credit cannot run in production")
    idempotency_key = f"demo-credit:{tenant_slug}:v1"
    async with session_factory() as session, session.begin():
        row = (
            await session.execute(
                select(Tenants, WalletAccounts)
                .join(WalletAccounts, WalletAccounts.tenant_id == Tenants.id)
                .where(
                    Tenants.slug == tenant_slug,
                    WalletAccounts.currency == "PTS",
                    WalletAccounts.status == "active",
                )
                .with_for_update(of=WalletAccounts)
            )
        ).first()
        if row is None:
            raise RuntimeError("demo tenant wallet was not found")
        tenant, wallet = row
        exists = (
            await session.execute(
                select(LedgerEntries.id).where(
                    LedgerEntries.tenant_id == tenant.id,
                    LedgerEntries.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            return
        wallet.balance_minor = int(wallet.balance_minor) + amount_minor
        wallet.version = int(wallet.version) + 1
        wallet.updated_at = datetime.now(UTC)
        session.add(
            LedgerEntries(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                wallet_account_id=wallet.id,
                reservation_id=None,
                entry_type="credit",
                amount_minor=amount_minor,
                currency="PTS",
                reference_type="demo_seed",
                reference_id=tenant.id,
                idempotency_key=idempotency_key,
                created_at=datetime.now(UTC),
            )
        )


async def _run_and_dispose(*, tenant_slug: str, amount_minor: int) -> None:
    try:
        await _run(tenant_slug=tenant_slug, amount_minor=amount_minor)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="mosaic-demo")
    parser.add_argument("--amount-minor", type=int, default=100_000)
    args = parser.parse_args(argv)
    if args.amount_minor < 1:
        raise ValueError("amount must be positive")
    asyncio.run(_run_and_dispose(tenant_slug=args.tenant, amount_minor=args.amount_minor))
    print("demo wallet credit: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
