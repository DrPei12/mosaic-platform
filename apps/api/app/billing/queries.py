"""PostgreSQL statement builders used by the billing service and unit tests."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Select, select

from app.infrastructure.models import BalanceReservations, WalletAccounts


def wallet_by_currency_for_update(tenant_id: UUID, currency: str) -> Select[Any]:
    return (
        select(WalletAccounts)
        .where(
            WalletAccounts.tenant_id == tenant_id,
            WalletAccounts.currency == currency,
        )
        .with_for_update()
    )


def wallet_by_id_for_update(tenant_id: UUID, wallet_id: UUID) -> Select[Any]:
    return (
        select(WalletAccounts)
        .where(
            WalletAccounts.tenant_id == tenant_id,
            WalletAccounts.id == wallet_id,
        )
        .with_for_update()
    )


def reservation_wallet_id(tenant_id: UUID, reservation_id: UUID) -> Select[Any]:
    return select(BalanceReservations.wallet_account_id).where(
        BalanceReservations.tenant_id == tenant_id,
        BalanceReservations.id == reservation_id,
    )


def reservation_by_id_for_update(tenant_id: UUID, reservation_id: UUID) -> Select[Any]:
    return (
        select(BalanceReservations)
        .where(
            BalanceReservations.tenant_id == tenant_id,
            BalanceReservations.id == reservation_id,
        )
        .with_for_update()
    )


def reservation_by_source(
    tenant_id: UUID,
    source_type: str,
    source_id: UUID,
    *,
    for_update: bool = False,
) -> Select[Any]:
    query = select(BalanceReservations).where(
        BalanceReservations.tenant_id == tenant_id,
        BalanceReservations.source_type == source_type,
        BalanceReservations.source_id == source_id,
    )
    return query.with_for_update() if for_update else query


__all__ = [
    "reservation_by_id_for_update",
    "reservation_by_source",
    "reservation_wallet_id",
    "wallet_by_currency_for_update",
    "wallet_by_id_for_update",
]
