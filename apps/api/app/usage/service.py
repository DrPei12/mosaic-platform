from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.auth.errors import AuthError
from app.auth.permissions import can_view_tenant_usage
from app.contracts.usage import (
    LedgerEntryResponse,
    UsageEntryResponse,
    UsageSummaryResponse,
    UsageTotals,
)
from app.infrastructure.models import (
    BalanceReservations,
    GenerationJobs,
    InferenceRequests,
    LedgerEntries,
    UsageRecords,
    WalletAccounts,
)

_RECENT_USAGE_LIMIT = 20
_RECENT_LEDGER_LIMIT = 20
_PTS_CURRENCY = "PTS"


class UsageService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        role: str,
    ) -> UsageSummaryResponse:
        """Return role-scoped usage plus bounded recent detail rows.

        Owner, admin, and billing_viewer receive tenant-wide totals and detail.
        Members receive only their own UsageRecords.  The wallet remains
        tenant-shared, while member ledger rows are limited to reservations
        whose chat/generation source is owned by the current actor; ledger
        credits or adjustments without a user-owned source stay hidden.

        The totals query intentionally aggregates the selected scope so the
        response remains exact; capping that query would silently change
        billing semantics.  The two detail queries are explicitly capped so
        their ORM result sets cannot grow with the tenant's history.
        """
        tenant_wide = can_view_tenant_usage(role)
        async with self._session.begin():
            wallet = (
                await self._session.execute(
                    select(WalletAccounts).where(
                        WalletAccounts.tenant_id == tenant_id,
                        WalletAccounts.currency == _PTS_CURRENCY,
                        WalletAccounts.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if wallet is None:
                raise AuthError(
                    status_code=503,
                    code="USAGE_UNAVAILABLE",
                    message="用量数据暂时不可用",
                    retryable=True,
                )
            usage_scope: list[ColumnElement[bool]] = [UsageRecords.tenant_id == tenant_id]
            if not tenant_wide:
                usage_scope.append(UsageRecords.actor_user_id == actor_user_id)

            totals = (
                await self._session.execute(
                    select(
                        func.count(UsageRecords.id),
                        func.coalesce(func.sum(UsageRecords.input_tokens), 0),
                        func.coalesce(func.sum(UsageRecords.output_tokens), 0),
                        func.coalesce(func.sum(UsageRecords.image_count), 0),
                        func.coalesce(func.sum(UsageRecords.video_seconds), 0),
                        func.coalesce(func.sum(UsageRecords.character_count), 0),
                        func.coalesce(func.sum(UsageRecords.storage_bytes), 0),
                        func.coalesce(func.sum(UsageRecords.charge_amount_minor), 0),
                    ).where(
                        *usage_scope,
                        UsageRecords.currency == wallet.currency,
                    )
                )
            ).one()
            usage_rows = tuple(
                (
                    await self._session.execute(
                        select(UsageRecords)
                        .where(
                            *usage_scope,
                            UsageRecords.currency == wallet.currency,
                        )
                        .order_by(UsageRecords.created_at.desc(), UsageRecords.id.desc())
                        .limit(_RECENT_USAGE_LIMIT)
                    )
                ).scalars()
            )
            ledger_scope: list[ColumnElement[bool]] = [
                LedgerEntries.tenant_id == tenant_id,
                LedgerEntries.currency == wallet.currency,
            ]
            if not tenant_wide:
                ledger_scope.append(
                    or_(
                        _member_chat_ledger_entry(tenant_id, actor_user_id),
                        _member_generation_ledger_entry(tenant_id, actor_user_id),
                    )
                )
            ledger_rows = tuple(
                (
                    await self._session.execute(
                        select(LedgerEntries)
                        .where(*ledger_scope)
                        .order_by(LedgerEntries.created_at.desc(), LedgerEntries.id.desc())
                        .limit(_RECENT_LEDGER_LIMIT)
                    )
                ).scalars()
            )
            return UsageSummaryResponse(
                currency=wallet.currency,
                balance_minor=int(wallet.balance_minor),
                reserved_minor=int(wallet.reserved_minor),
                totals=UsageTotals(
                    requests=int(totals[0]),
                    input_tokens=int(totals[1]),
                    output_tokens=int(totals[2]),
                    image_count=int(totals[3]),
                    video_seconds=int(totals[4]),
                    character_count=int(totals[5]),
                    storage_bytes=int(totals[6]),
                    charge_amount_minor=int(totals[7]),
                ),
                recent_usage=[
                    UsageEntryResponse(
                        usage_id=str(row.id),
                        source="chat" if row.inference_request_id is not None else "generation",
                        modality=row.modality,
                        model_id=row.model_key,
                        input_tokens=int(row.input_tokens),
                        output_tokens=int(row.output_tokens),
                        billable_units=int(row.billable_units),
                        charge_amount_minor=int(row.charge_amount_minor),
                        created_at=row.created_at,
                    )
                    for row in usage_rows
                ],
                recent_ledger=[
                    LedgerEntryResponse(
                        ledger_id=str(row.id),
                        entry_type=cast(
                            Literal["credit", "debit", "hold", "release", "adjustment"],
                            row.entry_type,
                        ),
                        amount_minor=int(row.amount_minor),
                        currency=row.currency,
                        reference_type=row.reference_type,
                        created_at=row.created_at,
                    )
                    for row in ledger_rows
                ],
            )


def _member_chat_ledger_entry(
    tenant_id: UUID,
    actor_user_id: UUID,
) -> ColumnElement[bool]:
    return (
        select(1)
        .select_from(BalanceReservations)
        .join(
            InferenceRequests,
            and_(
                InferenceRequests.tenant_id == BalanceReservations.tenant_id,
                InferenceRequests.id == BalanceReservations.source_id,
            ),
        )
        .where(
            BalanceReservations.tenant_id == tenant_id,
            BalanceReservations.id == LedgerEntries.reservation_id,
            BalanceReservations.source_type == "chat_inference",
            InferenceRequests.actor_user_id == actor_user_id,
        )
        .exists()
    )


def _member_generation_ledger_entry(
    tenant_id: UUID,
    actor_user_id: UUID,
) -> ColumnElement[bool]:
    return (
        select(1)
        .select_from(BalanceReservations)
        .join(
            GenerationJobs,
            and_(
                GenerationJobs.tenant_id == BalanceReservations.tenant_id,
                GenerationJobs.id == BalanceReservations.source_id,
            ),
        )
        .where(
            BalanceReservations.tenant_id == tenant_id,
            BalanceReservations.id == LedgerEntries.reservation_id,
            BalanceReservations.source_type == "generation",
            GenerationJobs.actor_user_id == actor_user_id,
        )
        .exists()
    )


__all__ = ["UsageService"]
