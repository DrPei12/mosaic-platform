"""Publish-outside-transaction fenced outbox relay."""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.messaging.rabbitmq import EventEnvelope, routing_key_for_outbox_event
from app.observability.metrics import record_outbox_outcome
from app.outbox.repository import OutboxRepository, normalize_event_types
from app.outbox.types import (
    ClaimedOutboxEvent,
    RetryPolicy,
    error_details_from_exception,
)


class OutboxPublisher(Protocol):
    async def publish(self, envelope: EventEnvelope) -> None: ...


@dataclass(frozen=True, slots=True)
class RelayBatchResult:
    claimed: int = 0
    published: int = 0
    retried: int = 0
    failed: int = 0
    fenced: int = 0
    skipped: int = 0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class FencedOutboxRelay:
    """Relay rows with lease-token fencing and bounded retry semantics.

    ``repository.claim`` must commit before it returns.  The relay then calls
    the publisher with no database transaction held, and performs a separate
    fenced mark transaction after the broker call completes.
    """

    def __init__(
        self,
        repository: OutboxRepository,
        publisher: OutboxPublisher,
        *,
        owner: str,
        event_types: str | Collection[str] | None = None,
        event_type: str | None = None,
        batch_size: int = 50,
        lease_seconds: int = 60,
        retry_policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not owner.strip() or len(owner.strip()) > 200:
            raise ValueError("outbox relay owner must be 1 to 200 characters")
        if not 1 <= batch_size <= 500:
            raise ValueError("outbox relay batch_size must be between 1 and 500")
        if lease_seconds < 1:
            raise ValueError("outbox relay lease_seconds must be positive")
        selected_types = normalize_event_types(event_types, event_type=event_type)
        self._repository = repository
        self._publisher = publisher
        self._owner = owner.strip()
        self._event_types = selected_types
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._retry_policy = retry_policy or RetryPolicy()
        self._clock = clock

    async def run_once(self, *, tenant_id: UUID | None = None) -> RelayBatchResult:
        """Claim a batch, publish it outside the DB transaction, then fence marks."""

        events = await self._repository.claim(
            owner=self._owner,
            event_types=self._event_types,
            limit=self._batch_size,
            tenant_id=tenant_id,
            lease_seconds=self._lease_seconds,
            max_attempts=self._retry_policy.max_attempts,
        )
        result = RelayBatchResult(claimed=len(events))
        for event in events:
            record_outbox_outcome(event_type=event.event_type, outcome="claimed")
            result = await self._process_one(event, result)
        return result

    async def relay_once(self, *, tenant_id: UUID | None = None) -> RelayBatchResult:
        """Vocabulary alias for callers that name the operation ``relay``."""

        return await self.run_once(tenant_id=tenant_id)

    async def _process_one(
        self,
        event: ClaimedOutboxEvent,
        result: RelayBatchResult,
    ) -> RelayBatchResult:
        if self._event_types is not None and event.event_type not in self._event_types:
            return _increment(result, "skipped")
        if event.claim_owner != self._owner:
            record_outbox_outcome(event_type=event.event_type, outcome="fenced")
            return _increment(result, "fenced")
        try:
            owner, lease_token = event.require_lease()
            envelope = EventEnvelope(
                event_id=event.event_id,
                tenant_id=event.tenant_id,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                event_type=event.event_type,
                aggregate_version=event.aggregate_version,
                routing_key=routing_key_for_outbox_event(
                    event.event_type,
                    event.payload,
                ),
            )
            # This is deliberately outside any repository/session transaction.
            await self._publisher.publish(envelope)
        except Exception as error:  # noqa: BLE001 - publish failures are classified safely
            if not event.claimed:
                record_outbox_outcome(event_type=event.event_type, outcome="fenced")
                return _increment(result, "fenced")
            owner, lease_token = event.require_lease()
            details = error_details_from_exception(
                error,
                default_retryable=not isinstance(error, ValueError),
            )
            retry_at = self._clock()
            if self._retry_policy.should_retry(
                attempts=event.attempts,
                retryable=details.retryable,
            ):
                retry_at += timedelta(seconds=self._retry_policy.delay_seconds(event.attempts))
            marked = await self._repository.mark_retry(
                tenant_id=event.tenant_id,
                event_id=event.event_id,
                aggregate_version=event.aggregate_version,
                owner=owner,
                lease_token=lease_token,
                details=details,
                retry_at=retry_at,
                max_attempts=self._retry_policy.max_attempts,
            )
            if not marked:
                record_outbox_outcome(event_type=event.event_type, outcome="fenced")
                return _increment(result, "fenced")
            if self._retry_policy.should_retry(
                attempts=event.attempts,
                retryable=details.retryable,
            ):
                record_outbox_outcome(event_type=event.event_type, outcome="retry")
                return _increment(result, "retried")
            record_outbox_outcome(event_type=event.event_type, outcome="failed")
            return _increment(result, "failed")

        marked = await self._repository.mark_published(
            tenant_id=event.tenant_id,
            event_id=event.event_id,
            aggregate_version=event.aggregate_version,
            owner=owner,
            lease_token=lease_token,
        )
        if not marked:
            record_outbox_outcome(event_type=event.event_type, outcome="fenced")
            return _increment(result, "fenced")
        record_outbox_outcome(event_type=event.event_type, outcome="published")
        return _increment(result, "published")


def _increment(result: RelayBatchResult, field: str) -> RelayBatchResult:
    values = {
        "claimed": result.claimed,
        "published": result.published,
        "retried": result.retried,
        "failed": result.failed,
        "fenced": result.fenced,
        "skipped": result.skipped,
    }
    values[field] += 1
    return RelayBatchResult(**values)


OutboxRelay = FencedOutboxRelay


__all__ = ["FencedOutboxRelay", "OutboxPublisher", "OutboxRelay", "RelayBatchResult"]
