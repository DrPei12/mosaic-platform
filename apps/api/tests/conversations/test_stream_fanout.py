from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from uuid import UUID

import pytest

from app.api.conversations import _sse_body
from app.conversations.ports import ChatRequestRecord, StreamEventRecord
from app.conversations.service import ConversationService
from app.infrastructure.redis import RedisChatStreamNotifier

TENANT_ID = UUID("00000000-0000-0000-0000-0000000000a1")
USER_ID = UUID("00000000-0000-0000-0000-0000000000a2")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-0000000000c1")
REQUEST_ID = UUID("00000000-0000-0000-0000-0000000000e1")
MESSAGE_ID = UUID("00000000-0000-0000-0000-0000000000d1")


def _request(*, status: str = "running", last_sequence: int = 0) -> ChatRequestRecord:
    return ChatRequestRecord(
        request_db_id=UUID("00000000-0000-0000-0000-0000000000f1"),
        request_id=REQUEST_ID,
        conversation_id=CONVERSATION_ID,
        message_id=MESSAGE_ID,
        tenant_id=TENANT_ID,
        status=status,
        last_event_sequence=last_sequence,
    )


def _event(sequence: int, event_type: str) -> StreamEventRecord:
    payload: dict[str, object] = {
        "type": event_type,
        "request_id": str(REQUEST_ID),
        "conversation_id": str(CONVERSATION_ID),
        "message_id": str(MESSAGE_ID),
        "sequence": sequence,
    }
    if event_type == "completed":
        payload["content"] = "answer"
    return StreamEventRecord(sequence=sequence, event=payload)


class StreamRepository:
    def __init__(self) -> None:
        self.request = _request()
        self.rows = [_event(0, "started")]
        self.event_calls = 0
        self.assert_calls = 0

    async def assert_request(self, **kwargs: object) -> ChatRequestRecord:
        assert kwargs["tenant_id"] == TENANT_ID
        assert kwargs["conversation_id"] == CONVERSATION_ID
        assert kwargs["request_id"] == REQUEST_ID
        self.assert_calls += 1
        return self.request

    async def events(self, **kwargs: object) -> tuple[StreamEventRecord, ...]:
        assert kwargs["tenant_id"] == TENANT_ID
        assert kwargs["conversation_id"] == CONVERSATION_ID
        assert kwargs["request_id"] == REQUEST_ID
        self.event_calls += 1
        after_sequence = int(kwargs["after_sequence"])
        return tuple(row for row in self.rows if row.sequence > after_sequence)


class WakeSubscription:
    def __init__(self, *, wait_error: Exception | None = None) -> None:
        self.signals: asyncio.Queue[bool] = asyncio.Queue()
        self.wait_error = wait_error
        self.waits: list[float] = []
        self.opened = False
        self.closed = False

    async def open(self) -> None:
        self.opened = True

    async def wait(self, timeout_seconds: float) -> bool:
        self.waits.append(timeout_seconds)
        if self.wait_error is not None:
            error = self.wait_error
            self.wait_error = None
            raise error
        try:
            return await asyncio.wait_for(self.signals.get(), timeout_seconds)
        except TimeoutError:
            return False

    async def close(self) -> None:
        self.closed = True


class WakeNotifier:
    def __init__(self, subscription: WakeSubscription) -> None:
        self.subscription = subscription
        self.published: list[tuple[UUID, UUID, int]] = []

    def subscribe(self, **_: object) -> WakeSubscription:
        return self.subscription

    async def publish(self, *, tenant_id: UUID, request_id: UUID, sequence: int) -> None:
        self.published.append((tenant_id, request_id, sequence))


class _FakeStreamPermit:
    def __init__(self) -> None:
        self.lost = False
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True


class BlockingStreamService:
    async def stream(self, **_: object):
        yield {
            "type": "started",
            "request_id": str(REQUEST_ID),
            "conversation_id": str(CONVERSATION_ID),
            "message_id": str(MESSAGE_ID),
            "sequence": 0,
        }
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_stream_repairs_lost_and_duplicate_notifications_with_db_replay() -> None:
    repository = StreamRepository()
    subscription = WakeSubscription()
    service = ConversationService(
        repository,  # type: ignore[arg-type]
        stream_notifier=WakeNotifier(subscription),  # type: ignore[arg-type]
        stream_max_duration_seconds=1,
        stream_replay_fallback_seconds=0.05,
    )
    iterator = service.stream(
        tenant_id=TENANT_ID,
        actor_user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        request_id=REQUEST_ID,
    ).__aiter__()

    first = await iterator.__anext__()
    assert first is not None
    assert first["sequence"] == 0
    waiting = asyncio.create_task(iterator.__anext__())
    for _ in range(20):
        if subscription.waits:
            break
        await asyncio.sleep(0)
    assert subscription.waits
    calls_before_wait = repository.event_calls
    await asyncio.sleep(0.01)
    assert repository.event_calls == calls_before_wait

    # Two wake-ups with no new DB row must not emit a duplicate event.
    await subscription.signals.put(True)
    await subscription.signals.put(True)
    for _ in range(20):
        if repository.event_calls >= calls_before_wait + 2:
            break
        await asyncio.sleep(0)
    assert repository.event_calls >= calls_before_wait + 2
    assert not waiting.done()

    repository.rows.append(_event(1, "completed"))
    repository.request = replace(repository.request, status="succeeded", last_event_sequence=1)
    # A timeout means the notification was lost; replay must still find the
    # committed row. The cursor prevents the two earlier duplicate wakes from
    # producing duplicate SSE events.
    await subscription.signals.put(False)
    second = await waiting
    assert second is not None
    assert second["sequence"] == 1
    await iterator.aclose()
    assert subscription.closed is True


@pytest.mark.asyncio
async def test_redis_wait_failure_uses_slow_replay_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = StreamRepository()
    subscription = WakeSubscription(wait_error=OSError("redis dropped"))
    service = ConversationService(
        repository,  # type: ignore[arg-type]
        stream_notifier=WakeNotifier(subscription),  # type: ignore[arg-type]
        stream_max_duration_seconds=0.035,
        stream_replay_fallback_seconds=0.01,
    )
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)
        await real_sleep(delay)

    monkeypatch.setattr("app.conversations.service.asyncio.sleep", record_sleep)
    events = [
        event
        async for event in service.stream(
            tenant_id=TENANT_ID,
            actor_user_id=USER_ID,
            conversation_id=CONVERSATION_ID,
            request_id=REQUEST_ID,
        )
    ]

    assert [event["sequence"] for event in events] == [0]
    assert subscription.closed is True
    assert sleeps
    assert sleeps[0] >= 0.009
    assert all(delay > 0.001 for delay in sleeps)
    assert repository.event_calls <= 5


@pytest.mark.asyncio
async def test_client_disconnect_releases_stream_permit() -> None:
    permit = _FakeStreamPermit()
    iterator = _sse_body(
        BlockingStreamService(),  # type: ignore[arg-type]
        tenant_id=TENANT_ID,
        actor_user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        request_id=REQUEST_ID,
        cursor=None,
        admission=permit,  # type: ignore[arg-type]
    ).__aiter__()

    first = await iterator.__anext__()
    assert "id: 0" in first
    assert permit.started is True
    pending = asyncio.create_task(iterator.__anext__())
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert permit.closed is True


class FakePubSub:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def get_message(self, *, ignore_subscribe_messages: bool, timeout: float) -> object:
        del ignore_subscribe_messages, timeout
        if not self.messages:
            return None
        return self.messages.pop(0)

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed.append(channel)

    async def aclose(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self) -> None:
        self.pubsub_instance = FakePubSub()
        self.published: list[tuple[str, str]] = []

    def pubsub(self) -> FakePubSub:
        return self.pubsub_instance

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1


@pytest.mark.asyncio
async def test_redis_notification_contains_only_replay_coordinates() -> None:
    client = FakeRedis()
    notifier = RedisChatStreamNotifier(client, environment="test")  # type: ignore[arg-type]

    await notifier.publish(tenant_id=TENANT_ID, request_id=REQUEST_ID, sequence=4)
    channel, raw_payload = client.published[0]
    payload = json.loads(raw_payload)
    assert channel.endswith(f":{TENANT_ID}:{REQUEST_ID}")
    assert payload == {"request_id": str(REQUEST_ID), "sequence": 4}
    assert "content" not in raw_payload
    assert "delta" not in raw_payload

    subscription = notifier.subscribe(tenant_id=TENANT_ID, request_id=REQUEST_ID)
    await subscription.open()
    client.pubsub_instance.messages.append({"type": "message", "data": b"wake"})
    assert await subscription.wait(0.1) is True
    await subscription.close()
    assert client.pubsub_instance.closed is True
