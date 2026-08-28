from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.conversations.ports import (
    ChatDeploymentRecord,
    ChatExecutionRecord,
    ChatExecutionRepository,
    ChatLeaseCheck,
    ChatUsageRecord,
    ConversationMessageRecord,
    StreamEventRecord,
)
from app.conversations.worker import ChatWorkerDependencies, DurableChatWorker
from app.infrastructure.concurrency import ConcurrencySaturated
from app.providers.errors import ProviderError
from app.providers.ports import TextCompletionRequest, TextGenerationPort, TextStreamChunk, Usage

TENANT_ID = UUID("00000000-0000-0000-0000-0000000000a1")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-0000000000c1")
REQUEST_ID = UUID("00000000-0000-0000-0000-0000000000e1")
MESSAGE_ID = UUID("00000000-0000-0000-0000-0000000000d1")


def _history() -> tuple[ConversationMessageRecord, ...]:
    now = datetime.now(UTC)
    return (
        ConversationMessageRecord(
            message_id=uuid4(),
            role="user",
            content="hello",
            status="accepted",
            created_at=now,
        ),
        ConversationMessageRecord(
            message_id=MESSAGE_ID,
            role="assistant",
            content="",
            status="streaming",
            created_at=now,
            request_id=REQUEST_ID,
        ),
    )


def _execution(*, status: str = "queued") -> ChatExecutionRecord:
    return ChatExecutionRecord(
        request_db_id=uuid4(),
        request_id=REQUEST_ID,
        conversation_id=CONVERSATION_ID,
        message_id=MESSAGE_ID,
        tenant_id=TENANT_ID,
        product_model_id="qwen3.5-plus",
        deployment=ChatDeploymentRecord(
            deployment_id=uuid4(),
            product_model_id="qwen3.5-plus",
            provider_model_id="qwen3.5-plus",
        ),
        history=_history(),
        status=status,
        last_event_sequence=0,
        reservation_id=uuid4(),
    )


class InMemoryExecutionRepository(ChatExecutionRepository):
    """State-machine fake; it models CAS/fencing but never claims live SQL."""

    def __init__(self, execution: ChatExecutionRecord) -> None:
        self.execution = execution
        self.content = ""
        self.events: list[StreamEventRecord] = [
            StreamEventRecord(
                0,
                {
                    "type": "started",
                    "request_id": str(execution.request_id),
                    "conversation_id": str(execution.conversation_id),
                    "message_id": str(execution.message_id),
                    "sequence": 0,
                },
            )
        ]
        self.calls: list[str] = []
        self.lease_lost_after_deltas: int | None = None
        self.stop_after_checks: int | None = None
        self.check_count = 0
        self.delta_count = 0
        self.usage: ChatUsageRecord | None = None

    async def claim_queued(self, *, worker_id, lease_seconds, tenant_id=None, request_id=None):
        self.calls.append("claim")
        if self.execution.status != "queued":
            return None
        if tenant_id is not None and tenant_id != self.execution.tenant_id:
            return None
        if request_id is not None and request_id != self.execution.request_id:
            return None
        token = uuid4()
        self.execution = replace(
            self.execution,
            status="running",
            worker_id=worker_id,
            lease_token=token,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
        )
        return self.execution

    async def requeue_claimed(self, *, execution):
        if not self._fenced(execution):
            return False
        self.calls.append("requeue")
        self.execution = replace(
            self.execution,
            status="queued",
            worker_id=None,
            lease_token=None,
            lease_expires_at=None,
        )
        return True

    async def check_lease_and_stop(self, *, execution):
        self.calls.append("check")
        self.check_count += 1
        valid = execution.lease_token == self.execution.lease_token
        if self.lease_lost_after_deltas is not None and self.delta_count >= self.lease_lost_after_deltas:
            valid = False
        stop = (
            self.stop_after_checks is not None
            and self.check_count >= self.stop_after_checks
        )
        return ChatLeaseCheck(lease_valid=valid, stop_requested=stop)

    def _fenced(self, execution: ChatExecutionRecord) -> bool:
        return (
            execution.lease_token is not None
            and execution.lease_token == self.execution.lease_token
            and self.execution.status == "running"
        )

    async def append_delta(self, *, execution, expected_sequence, delta, provider_request_id):
        self.calls.append("delta")
        if not self._fenced(execution) or expected_sequence != self.execution.last_event_sequence + 1:
            return None
        self.content += delta
        self.delta_count += 1
        event = StreamEventRecord(
            expected_sequence,
            {
                "type": "delta",
                "request_id": str(self.execution.request_id),
                "conversation_id": str(self.execution.conversation_id),
                "message_id": str(self.execution.message_id),
                "sequence": expected_sequence,
                "delta": delta,
            },
        )
        self.events.append(event)
        self.execution = replace(
            self.execution,
            last_event_sequence=expected_sequence,
            provider_request_id=provider_request_id,
        )
        return event

    async def mark_completed(
        self,
        *,
        execution,
        expected_sequence,
        content,
        provider_request_id,
        usage,
    ):
        self.calls.append("completed")
        if not self._fenced(execution) or expected_sequence != self.execution.last_event_sequence + 1:
            return False
        self.content = content
        self.usage = usage
        self.execution = replace(
            self.execution,
            status="succeeded",
            last_event_sequence=expected_sequence,
            provider_request_id=provider_request_id,
        )
        self.events.append(
            StreamEventRecord(
                expected_sequence,
                {
                    "type": "completed",
                    "request_id": str(self.execution.request_id),
                    "conversation_id": str(self.execution.conversation_id),
                    "message_id": str(self.execution.message_id),
                    "sequence": expected_sequence,
                    "content": content,
                },
            )
        )
        return True

    async def mark_stopped(self, *, execution, expected_sequence, content):
        self.calls.append("stopped")
        if not self._fenced(execution) or expected_sequence != self.execution.last_event_sequence + 1:
            return False
        self.content = content
        self.execution = replace(
            self.execution,
            status="stopped",
            last_event_sequence=expected_sequence,
        )
        self.events.append(
            StreamEventRecord(
                expected_sequence,
                {
                    "type": "stopped",
                    "request_id": str(self.execution.request_id),
                    "conversation_id": str(self.execution.conversation_id),
                    "message_id": str(self.execution.message_id),
                    "sequence": expected_sequence,
                },
            )
        )
        return True

    async def mark_failed(
        self,
        *,
        execution,
        expected_sequence,
        error_code,
        error_details,
        provider_request_id,
    ):
        del error_details
        self.calls.append("failed")
        if not self._fenced(execution) or expected_sequence != self.execution.last_event_sequence + 1:
            return False
        self.execution = replace(
            self.execution,
            status="failed",
            last_event_sequence=expected_sequence,
            provider_request_id=provider_request_id,
        )
        self.events.append(
            StreamEventRecord(
                expected_sequence,
                {
                    "type": "failed",
                    "request_id": str(self.execution.request_id),
                    "conversation_id": str(self.execution.conversation_id),
                    "message_id": str(self.execution.message_id),
                    "sequence": expected_sequence,
                    "error": {"code": error_code},
                },
            )
        )
        return True

    async def mark_submitted_unknown(self, *, execution, provider_request_id, error_code):
        del error_code
        self.calls.append("submitted_unknown")
        if not self._fenced(execution):
            return False
        self.execution = replace(
            self.execution,
            status="submitted_unknown",
            provider_request_id=provider_request_id,
        )
        return True


class FakeBilling:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def capture(self, *, execution, usage):
        del execution, usage
        self.calls.append("capture")

    async def release(self, *, execution):
        del execution
        self.calls.append("release")


class RecordingStreamNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, int]] = []

    async def publish(self, *, tenant_id: UUID, request_id: UUID, sequence: int) -> None:
        self.calls.append((tenant_id, request_id, sequence))


class FakeTextProvider(TextGenerationPort):
    def __init__(self, chunks: tuple[TextStreamChunk, ...], error: ProviderError | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.calls = 0
        self.requests: list[TextCompletionRequest] = []

    async def complete(self, request):
        raise AssertionError("worker must use stream, not complete")

    async def stream(self, request) -> AsyncIterator[TextStreamChunk]:
        self.calls += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            yield chunk


class _PermitLease:
    ttl_ms = 30_000

    def __init__(self) -> None:
        self.released = False

    async def renew(self) -> bool:
        return not self.released

    async def release(self) -> bool:
        if self.released:
            return False
        self.released = True
        return True


class _PermitSemaphore:
    def __init__(self, *, saturated: bool = False) -> None:
        self.saturated = saturated

    async def acquire(self, resource: str, *, limit: int, ttl_seconds: float):
        del resource, limit, ttl_seconds
        if self.saturated:
            return None
        return _PermitLease()


def _chunk(delta: str, *, usage: Usage | None = None) -> TextStreamChunk:
    return TextStreamChunk(
        request_id="provider-request-1",
        model="qwen3.5-plus",
        delta=delta,
        finish_reason=None,
        usage=usage,
    )


def _worker(repository, provider, billing, notifier=None) -> DurableChatWorker:
    return DurableChatWorker(
        ChatWorkerDependencies(
            repository=repository,
            text_generation=provider,
            billing=billing,
            concurrency=_PermitSemaphore(),
            stream_notifier=notifier,
            worker_id="worker-1",
        )
    )


@pytest.mark.asyncio
async def test_success_persists_each_delta_then_captures_usage() -> None:
    repository = InMemoryExecutionRepository(_execution())
    provider = FakeTextProvider(
        (
            _chunk("one "),
            _chunk("two", usage=Usage(prompt_tokens=3, completion_tokens=2, total_tokens=5)),
        )
    )
    billing = FakeBilling()

    await _worker(repository, provider, billing).run_once()

    assert provider.calls == 1
    assert [event.event["type"] for event in repository.events] == [
        "started",
        "delta",
        "delta",
        "completed",
    ]
    assert repository.content == "one two"
    assert repository.execution.status == "succeeded"
    assert repository.usage is not None
    assert repository.usage.usage.total_tokens == 5
    assert billing.calls == ["capture"]


@pytest.mark.asyncio
async def test_worker_notifies_only_after_each_durable_event_commit() -> None:
    repository = InMemoryExecutionRepository(_execution())
    provider = FakeTextProvider((_chunk("one"),))
    billing = FakeBilling()
    notifier = RecordingStreamNotifier()

    await _worker(repository, provider, billing, notifier).run_once()

    assert [sequence for _, _, sequence in notifier.calls] == [1, 2]
    assert all(request_id == REQUEST_ID for _, request_id, _ in notifier.calls)
    assert all(tenant_id == TENANT_ID for tenant_id, _, _ in notifier.calls)


@pytest.mark.asyncio
async def test_invalid_history_releases_the_acceptance_hold() -> None:
    execution = _execution()
    invalid_history = (
        ConversationMessageRecord(
            message_id=uuid4(),
            role="unknown",
            content="bad",
            status="accepted",
            created_at=datetime.now(UTC),
        ),
    )
    repository = InMemoryExecutionRepository(replace(execution, history=invalid_history))
    billing = FakeBilling()

    await _worker(repository, FakeTextProvider(()), billing).run_once()

    assert repository.execution.status == "failed"
    assert billing.calls == ["release"]


@pytest.mark.asyncio
async def test_saturated_chat_is_requeued_without_billing_or_provider_call() -> None:
    repository = InMemoryExecutionRepository(_execution())
    provider = FakeTextProvider((_chunk("must not run"),))
    billing = FakeBilling()
    worker = DurableChatWorker(
        ChatWorkerDependencies(
            repository=repository,
            text_generation=provider,
            billing=billing,
            concurrency=_PermitSemaphore(saturated=True),
            concurrency_retry_delay_seconds=0.05,
            worker_id="worker-1",
        )
    )

    with pytest.raises(ConcurrencySaturated):
        await worker.run_once()

    assert repository.execution.status == "queued"
    assert "requeue" in repository.calls
    assert provider.calls == 0
    assert billing.calls == []


@pytest.mark.asyncio
async def test_known_provider_failure_is_failed_and_releases_reservation() -> None:
    repository = InMemoryExecutionRepository(_execution())
    provider = FakeTextProvider(
        (),
        error=ProviderError(
            provider="dashscope",
            operation="text_stream",
            code="provider_bad_request",
            message="bad request",
            status_code=400,
        ),
    )
    billing = FakeBilling()

    await _worker(repository, provider, billing).run_once()

    assert repository.execution.status == "failed"
    assert repository.events[-1].event["type"] == "failed"
    assert billing.calls == ["release"]
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_unknown_submission_is_not_retried_or_released() -> None:
    repository = InMemoryExecutionRepository(_execution())
    provider = FakeTextProvider(
        (),
        error=ProviderError(
            provider="dashscope",
            operation="text_stream",
            code="provider_submission_unknown",
            message="outcome is unknown",
            retryable=False,
            request_id="provider-request-unknown",
        ),
    )
    billing = FakeBilling()
    worker = _worker(repository, provider, billing)

    await worker.run_once()
    claimed_again = await worker.run_once()

    assert claimed_again is False
    assert repository.execution.status == "submitted_unknown"
    assert repository.events[-1].event["type"] == "started"
    assert billing.calls == []
    assert provider.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        ProviderError(
            provider="dashscope",
            operation="text_stream",
            code="provider_http_error",
            message="provider unavailable",
            status_code=503,
        ),
        ProviderError(
            provider="dashscope",
            operation="text_stream",
            code="provider_http_error",
            message="provider request timed out",
            status_code=408,
        ),
        ProviderError(
            provider="dashscope",
            operation="text_stream",
            code="provider_protocol_error",
            message="stream ended without a terminal usage event",
        ),
    ],
)
async def test_ambiguous_server_or_protocol_failure_preserves_reservation(
    error: ProviderError,
) -> None:
    repository = InMemoryExecutionRepository(_execution())
    provider = FakeTextProvider((), error=error)
    billing = FakeBilling()

    await _worker(repository, provider, billing).run_once()

    assert repository.execution.status == "submitted_unknown"
    assert billing.calls == []
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_connection_not_established_is_failed_and_releases_reservation() -> None:
    repository = InMemoryExecutionRepository(_execution())
    provider = FakeTextProvider(
        (),
        error=ProviderError(
            provider="dashscope",
            operation="text_stream",
            code="provider_connection_error",
            message="connection could not be established",
            retryable=True,
        ),
    )
    billing = FakeBilling()

    await _worker(repository, provider, billing).run_once()

    assert repository.execution.status == "failed"
    assert billing.calls == ["release"]
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_stop_between_chunks_persists_stopped_and_releases() -> None:
    repository = InMemoryExecutionRepository(_execution())
    repository.stop_after_checks = 4
    provider = FakeTextProvider((_chunk("first"), _chunk("second")))
    billing = FakeBilling()

    await _worker(repository, provider, billing).run_once()

    assert repository.execution.status == "stopped"
    assert repository.content == "first"
    assert [event.event["type"] for event in repository.events] == [
        "started",
        "delta",
        "stopped",
    ]
    assert billing.calls == ["release"]


@pytest.mark.asyncio
async def test_lease_loss_after_first_delta_stops_all_further_writes() -> None:
    repository = InMemoryExecutionRepository(_execution())
    repository.lease_lost_after_deltas = 1
    provider = FakeTextProvider((_chunk("first"), _chunk("second")))
    billing = FakeBilling()

    await _worker(repository, provider, billing).run_once()

    assert repository.execution.status == "running"
    assert repository.content == "first"
    assert [event.event["type"] for event in repository.events] == [
        "started",
        "delta",
    ]
    assert billing.calls == []
