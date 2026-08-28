"""Chat worker capture/release adapter over the shared billing service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.errors import RESERVATION_EXPIRED, BillingConflict
from app.billing.ports import BillingUsage
from app.billing.service import SqlAlchemyBillingService
from app.conversations.ports import (
    ChatBillingSettlementPort,
    ChatExecutionRecord,
    ChatUsageRecord,
)
from app.infrastructure.models import BalanceReservations, InferenceRequests, UsageRecords

_SOURCE_TYPE = "chat_inference"


class SqlAlchemyChatBillingAdapter(ChatBillingSettlementPort):
    """Capture the acceptance-time hold using actual provider usage."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def capture(
        self,
        *,
        execution: ChatExecutionRecord,
        usage: ChatUsageRecord,
    ) -> None:
        reservation_id = await self._required_reservation_id(execution)
        async with self._sessions() as session:
            await SqlAlchemyBillingService(session).capture(
                tenant_id=execution.tenant_id,
                reservation_id=reservation_id,
                usage=_billing_usage(usage),
            )

    async def release(self, *, execution: ChatExecutionRecord) -> None:
        reservation_id = await self._required_reservation_id(execution)
        async with self._sessions() as session:
            await SqlAlchemyBillingService(session).release(
                tenant_id=execution.tenant_id,
                reservation_id=reservation_id,
            )

    async def reconcile_once(self, *, limit: int = 50) -> int:
        """Repair terminal request/reservation drift without provider retries."""

        if not 1 <= limit <= 500:
            raise ValueError("reconciliation limit must be between 1 and 500")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        BalanceReservations.tenant_id,
                        BalanceReservations.id,
                        InferenceRequests.status,
                        UsageRecords.id,
                    )
                    .join(
                        InferenceRequests,
                        and_(
                            InferenceRequests.tenant_id == BalanceReservations.tenant_id,
                            InferenceRequests.id == BalanceReservations.source_id,
                        ),
                    )
                    .outerjoin(
                        UsageRecords,
                        and_(
                            UsageRecords.tenant_id == InferenceRequests.tenant_id,
                            UsageRecords.inference_request_id == InferenceRequests.id,
                        ),
                    )
                    .where(
                        BalanceReservations.source_type == _SOURCE_TYPE,
                        BalanceReservations.status == "pending",
                        InferenceRequests.status.in_(
                            ("succeeded", "failed", "stopped", "cancelled")
                        ),
                    )
                    .order_by(BalanceReservations.created_at)
                    .limit(limit)
                )
            ).all()
        repaired = 0
        for tenant_id, reservation_id, status, usage_id in rows:
            if status == "succeeded" and usage_id is None:
                continue
            async with self._sessions() as session:
                service = SqlAlchemyBillingService(session)
                if status == "succeeded":
                    try:
                        await service.capture(
                            tenant_id=tenant_id,
                            reservation_id=reservation_id,
                        )
                    except BillingConflict as exc:
                        if exc.code != RESERVATION_EXPIRED:
                            raise
                        await service.release(
                            tenant_id=tenant_id,
                            reservation_id=reservation_id,
                        )
                else:
                    await service.release(
                        tenant_id=tenant_id,
                        reservation_id=reservation_id,
                    )
                repaired += 1
        return repaired

    async def _required_reservation_id(self, execution: ChatExecutionRecord) -> UUID:
        if execution.reservation_id is not None:
            return execution.reservation_id
        async with self._sessions() as session:
            reservation_id = (
                await session.execute(
                    select(BalanceReservations.id).where(
                        BalanceReservations.tenant_id == execution.tenant_id,
                        BalanceReservations.source_type == _SOURCE_TYPE,
                        BalanceReservations.source_id == execution.request_db_id,
                    )
                )
            ).scalar_one_or_none()
        if reservation_id is None:
            raise RuntimeError("chat billing reservation is missing")
        return reservation_id


def _billing_usage(usage: ChatUsageRecord) -> BillingUsage:
    provider_usage = usage.usage
    return BillingUsage(
        input_tokens=provider_usage.prompt_tokens,
        output_tokens=provider_usage.completion_tokens,
        billable_units=provider_usage.total_tokens,
    )


# Kept only so existing worker entrypoints can adopt the new capture-only
# implementation without changing operational wiring in this slice.
PromotionalChatBillingAdapter = SqlAlchemyChatBillingAdapter


__all__ = ["PromotionalChatBillingAdapter", "SqlAlchemyChatBillingAdapter"]
