from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.messaging.rabbitmq import (
    GENERATION_ROUTING_KEY,
    VIDEO_GENERATION_ROUTING_KEY,
    EventEnvelope,
)
from app.outbox.relay import FencedOutboxRelay, RelayBatchResult
from app.outbox.types import ClaimedOutboxEvent, OutboxErrorDetails, RetryPolicy

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def event(
    *,
    event_type: str = "generation.accepted",
    attempts: int = 1,
    owner: str = "relay-a",
    token: UUID | None = None,
    modality: str = "image",
) -> ClaimedOutboxEvent:
    return ClaimedOutboxEvent(
        event_id=uuid4(),
        tenant_id=TENANT_ID,
        aggregate_type="generation_job",
        aggregate_id=uuid4(),
        event_type=event_type,
        aggregate_version=1,
        payload={"prompt": "must stay in the DB", "modality": modality},
        attempts=attempts,
        claim_owner=owner,
        lease_token=token or uuid4(),
        lease_expires_at=NOW,
    )


class FakeRepository:
    def __init__(self, events: Sequence[ClaimedOutboxEvent]) -> None:
        self.events = tuple(events)
        self.claim_calls: list[dict[str, object]] = []
        self.mark_calls: list[tuple[str, dict[str, object]]] = []
        self.allow_mark = True
        self.publishing = False

    async def claim(self, **kwargs: object) -> Sequence[ClaimedOutboxEvent]:
        assert self.publishing is False
        self.claim_calls.append(kwargs)
        return self.events

    async def mark_published(self, **kwargs: object) -> bool:
        assert self.publishing is False
        self.mark_calls.append(("published", kwargs))
        return self.allow_mark

    async def mark_retry(self, **kwargs: object) -> bool:
        assert self.publishing is False
        self.mark_calls.append(("retry", kwargs))
        return self.allow_mark


class FakePublisher:
    def __init__(self, repository: FakeRepository, *, error: Exception | None = None) -> None:
        self.repository = repository
        self.error = error
        self.envelopes: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> None:
        assert self.repository.publishing is False
        self.repository.publishing = True
        try:
            self.envelopes.append(envelope)
            if self.error is not None:
                raise self.error
        finally:
            self.repository.publishing = False


@pytest.mark.asyncio
async def test_relay_filters_event_types_and_marks_success_after_publish() -> None:
    selected = event()
    ignored = event(event_type="chat.inference.execute")
    repository = FakeRepository([selected, ignored])
    publisher = FakePublisher(repository)
    relay = FencedOutboxRelay(
        repository,  # type: ignore[arg-type]
        publisher,
        owner="relay-a",
        event_type="generation.accepted",
        clock=lambda: NOW,
    )

    result = await relay.run_once()

    assert result == RelayBatchResult(claimed=2, published=1, skipped=1)
    assert repository.claim_calls[0]["event_types"] == ("generation.accepted",)
    assert repository.mark_calls[0][0] == "published"
    assert publisher.envelopes[0].event_type == "generation.accepted"
    assert publisher.envelopes[0].routing_key == GENERATION_ROUTING_KEY
    assert b"prompt" not in publisher.envelopes[0].body()


@pytest.mark.asyncio
async def test_relay_assigns_video_to_the_video_transport_route() -> None:
    repository = FakeRepository([event(modality="video")])
    publisher = FakePublisher(repository)
    relay = FencedOutboxRelay(
        repository,  # type: ignore[arg-type]
        publisher,
        owner="relay-a",
        event_type="generation.accepted",
        clock=lambda: NOW,
    )

    result = await relay.run_once()

    assert result == RelayBatchResult(claimed=1, published=1)
    assert publisher.envelopes[0].routing_key == VIDEO_GENERATION_ROUTING_KEY


@pytest.mark.asyncio
async def test_publish_failure_is_retried_with_bounded_exponential_delay_and_safe_error() -> None:
    selected = event(attempts=2)
    repository = FakeRepository([selected])

    class BrokerError(RuntimeError):
        code = "BROKER_TIMEOUT"

    publisher = FakePublisher(repository, error=BrokerError("prompt=never persist this"))
    relay = FencedOutboxRelay(
        repository,  # type: ignore[arg-type]
        publisher,
        owner="relay-a",
        retry_policy=RetryPolicy(max_attempts=5, base_seconds=2, max_seconds=10),
        clock=lambda: NOW,
    )

    result = await relay.run_once()

    assert result == RelayBatchResult(claimed=1, retried=1)
    kind, kwargs = repository.mark_calls[0]
    assert kind == "retry"
    assert kwargs["retry_at"] == datetime(2026, 8, 24, 12, 0, 4, tzinfo=UTC)
    details = kwargs["details"]
    assert isinstance(details, OutboxErrorDetails)
    assert details.as_mapping() == {
        "code": "BROKER_TIMEOUT",
        "phase": "publish",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_max_attempt_and_stale_fence_are_terminal_or_fenced() -> None:
    selected = event(attempts=3)
    repository = FakeRepository([selected])
    publisher = FakePublisher(repository, error=RuntimeError("provider body"))
    relay = FencedOutboxRelay(
        repository,
        publisher,
        owner="relay-a",
        retry_policy=RetryPolicy(max_attempts=3, base_seconds=1, max_seconds=10),
        clock=lambda: NOW,
    )  # type: ignore[arg-type]

    result = await relay.run_once()
    assert result == RelayBatchResult(claimed=1, failed=1)
    assert repository.mark_calls[0][1]["retry_at"] == NOW

    repository = FakeRepository([event()])
    repository.allow_mark = False
    publisher = FakePublisher(repository)
    relay = FencedOutboxRelay(repository, publisher, owner="relay-a")  # type: ignore[arg-type]
    result = await relay.run_once()
    assert result == RelayBatchResult(claimed=1, fenced=1)
