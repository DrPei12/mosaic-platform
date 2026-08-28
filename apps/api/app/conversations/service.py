"""Application service for durable tenant-scoped conversations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from app.contracts.conversation import (
    ChatStreamEvent,
    ConversationMessage,
    ConversationResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    RegenerateMessageRequest,
    SendMessageRequest,
)
from app.conversations.errors import (
    ChatSubmissionDisabledError,
    ConversationInfrastructureError,
    ConversationNotFoundError,
    StreamCapacityError,
    StreamCursorError,
)
from app.conversations.ports import (
    AcceptedChatRequest,
    ChatRequestRecord,
    ChatStreamAdmission,
    ChatStreamNotifier,
    ChatStreamPermit,
    ConversationRecord,
    ConversationRepository,
    StopResult,
    StreamEventRecord,
)
from app.infrastructure.concurrency import ConcurrencyUnavailable
from app.observability.metrics import (
    record_redis_notification_loss,
    record_sse_replay_fallback,
)

_EVENT_ADAPTER: TypeAdapter[ChatStreamEvent] = TypeAdapter(ChatStreamEvent)
_TERMINAL_EVENT_TYPES = frozenset({"completed", "stopped", "failed"})
_TERMINAL_REQUEST_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "stopped", "submitted_unknown"}
)


def canonical_request_hash(payload: Mapping[str, object]) -> str:
    """Hash only normalized public fields; prompt text never enters outbox data."""

    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        *,
        submission_enabled: bool = False,
        stream_notifier: ChatStreamNotifier | None = None,
        stream_admission: ChatStreamAdmission | None = None,
        stream_max_duration_seconds: float | None = 300.0,
        stream_replay_fallback_seconds: float = 5.0,
        # Kept as a source-compatible alias for controlled tests and callers
        # that used the old transport deadline name. It is not a poll rate.
        stream_poll_deadline_seconds: float | None = None,
    ) -> None:
        max_duration = (
            stream_poll_deadline_seconds
            if stream_poll_deadline_seconds is not None
            else stream_max_duration_seconds
        )
        if max_duration is not None and max_duration < 0:
            raise ValueError("stream maximum duration must be non-negative")
        if stream_replay_fallback_seconds <= 0 or stream_replay_fallback_seconds > 5:
            raise ValueError("stream replay fallback must be between 0 and 5 seconds")
        self._repository = repository
        self._submission_enabled = submission_enabled
        self._stream_notifier = stream_notifier
        self._stream_admission = stream_admission
        self._stream_max_duration_seconds = max_duration
        self._stream_replay_fallback_seconds = stream_replay_fallback_seconds

    async def list(
        self, *, tenant_id: UUID, actor_user_id: UUID, limit: int = 50
    ) -> list[ConversationSummaryResponse]:
        records = await self._repository.list(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            limit=limit,
        )
        return [self._summary_response(record) for record in records]

    async def get(
        self, *, tenant_id: UUID, actor_user_id: UUID, conversation_id: UUID
    ) -> ConversationResponse:
        record = await self._repository.get(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            conversation_id=conversation_id,
        )
        if record is None:
            raise ConversationNotFoundError()
        return self._response(record)

    async def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        request: CreateConversationRequest,
    ) -> ConversationResponse:
        record, _replayed = await self._repository.create(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            product_model_id=request.product_model_id,
            client_request_id=request.client_request_id,
            request_hash=canonical_request_hash(
                {
                    "product_model_id": request.product_model_id,
                }
            ),
        )
        return self._response(record)

    async def send(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
        request: SendMessageRequest,
    ) -> AcceptedChatRequest:
        self._require_submission_enabled()
        accepted = await self._repository.submit(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            conversation_id=conversation_id,
            content=request.content,
            client_request_id=request.client_request_id,
            request_hash=canonical_request_hash(
                {
                    "conversation_id": str(conversation_id),
                    "content": request.content,
                }
            ),
        )
        if not accepted.replayed:
            await self._notify_stream_event(accepted.request)
        return accepted

    async def regenerate(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        request: RegenerateMessageRequest,
    ) -> AcceptedChatRequest:
        self._require_submission_enabled()
        accepted = await self._repository.regenerate(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            client_request_id=request.client_request_id,
            request_hash=canonical_request_hash(
                {
                    "conversation_id": str(conversation_id),
                    "message_id": str(message_id),
                }
            ),
        )
        if not accepted.replayed:
            await self._notify_stream_event(accepted.request)
        return accepted

    async def acquire_stream_admission(
        self,
        *,
        tenant_id: UUID,
    ) -> ChatStreamPermit | None:
        """Acquire the HTTP stream lease before a streaming response is accepted."""

        if self._stream_admission is None:
            return None
        try:
            permit = await self._stream_admission.acquire(tenant_id=tenant_id)
        except ConcurrencyUnavailable as exc:
            raise ConversationInfrastructureError("STREAM_ADMISSION_UNAVAILABLE") from exc
        if permit is None:
            raise StreamCapacityError()
        return permit

    async def stop(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
        request_id: UUID,
    ) -> StopResult:
        result = await self._repository.stop(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            conversation_id=conversation_id,
            request_id=request_id,
        )
        if result.changed and result.last_event_sequence is not None:
            await self._notify_stream(
                tenant_id=tenant_id,
                request_id=request_id,
                sequence=result.last_event_sequence,
            )
        return result

    async def assert_stream_request(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
        request_id: UUID,
    ) -> ChatRequestRecord:
        return await self._repository.assert_request(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            conversation_id=conversation_id,
            request_id=request_id,
        )

    async def stream(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
        request_id: UUID,
        cursor: int | None = None,
        include_heartbeats: bool = False,
        heartbeat_interval_seconds: float = 15.0,
    ) -> AsyncIterator[dict[str, object] | None]:
        """Replay committed events and wait for Redis wake-ups with DB fallback.

        Redis messages are deliberately incomplete hints. Every yielded event
        is read and validated from PostgreSQL, and a lost/duplicate message is
        repaired or deduplicated by the cursor. When Redis is unavailable the
        generator sleeps before each bounded replay attempt; it never falls
        back to a hot DB poll loop.
        """

        normalized_cursor = -1 if cursor is None else cursor
        if normalized_cursor < -1 or (include_heartbeats and heartbeat_interval_seconds <= 0):
            raise StreamCursorError()
        # Validate tenant/conversation/request ownership before yielding any
        # bytes.  A request ID is never accepted without this lookup.
        request = await self._repository.assert_request(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            conversation_id=conversation_id,
            request_id=request_id,
        )
        if request.status in _TERMINAL_REQUEST_STATUSES and request.last_event_sequence < 1:
            raise ConversationInfrastructureError("STREAM_TERMINAL_EVENT_MISSING")
        if normalized_cursor > request.last_event_sequence:
            raise StreamCursorError()
        expected = normalized_cursor + 1
        terminal = False
        started = normalized_cursor >= 0
        deadline = (
            None
            if self._stream_max_duration_seconds is None
            else time.monotonic() + self._stream_max_duration_seconds
        )
        if (
            request.status in _TERMINAL_REQUEST_STATUSES
            and normalized_cursor >= request.last_event_sequence
        ):
            return
        last_heartbeat = time.monotonic()
        subscription = None
        candidate = None
        if self._stream_notifier is not None:
            try:
                candidate = self._stream_notifier.subscribe(
                    tenant_id=tenant_id,
                    request_id=request.request_id,
                )
                await candidate.open()
                subscription = candidate
            except Exception:  # noqa: BLE001 - replay fallback covers Redis loss
                if candidate is not None:
                    with suppress(Exception):
                        await candidate.close()
                record_sse_replay_fallback(reason="subscription_open")
                record_redis_notification_loss()

        try:
            while True:
                rows = await self._repository.events(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    conversation_id=conversation_id,
                    request_id=request.request_id,
                    after_sequence=expected - 1,
                )
                for row in rows:
                    event = self._validate_event(
                        row,
                        request_id=request.request_id,
                        conversation_id=conversation_id,
                        message_id=request.message_id,
                        expected_sequence=expected,
                        require_started=not started,
                        terminal=terminal,
                    )
                    started = True
                    expected += 1
                    if event["type"] in _TERMINAL_EVENT_TYPES:
                        terminal = True
                    yield event
                if terminal:
                    return
                refreshed = await self._repository.assert_request(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    conversation_id=conversation_id,
                    request_id=request.request_id,
                )
                if (
                    refreshed.status in _TERMINAL_REQUEST_STATUSES
                    and expected > refreshed.last_event_sequence
                ):
                    return
                if (
                    not rows
                    and refreshed.status in _TERMINAL_REQUEST_STATUSES
                    and expected <= refreshed.last_event_sequence
                ):
                    raise ConversationInfrastructureError("STREAM_EVENT_SEQUENCE_INVALID")
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return
                else:
                    remaining = self._stream_replay_fallback_seconds
                wait_seconds = min(self._stream_replay_fallback_seconds, remaining)
                if include_heartbeats:
                    heartbeat_remaining = heartbeat_interval_seconds - (
                        time.monotonic() - last_heartbeat
                    )
                    if heartbeat_remaining <= 0:
                        last_heartbeat = time.monotonic()
                        yield None
                        continue
                    wait_seconds = min(wait_seconds, heartbeat_remaining)
                if wait_seconds <= 0:
                    return
                if subscription is None:
                    await asyncio.sleep(wait_seconds)
                else:
                    try:
                        await subscription.wait(wait_seconds)
                    except Exception:  # noqa: BLE001 - close Redis and use slow replay
                        with suppress(Exception):
                            await subscription.close()
                        subscription = None
                        record_sse_replay_fallback(reason="subscription_wait")
                        record_redis_notification_loss()
                        await asyncio.sleep(wait_seconds)
                if (
                    include_heartbeats
                    and time.monotonic() - last_heartbeat >= heartbeat_interval_seconds
                ):
                    last_heartbeat = time.monotonic()
                    yield None
        finally:
            if subscription is not None:
                with suppress(Exception):
                    await subscription.close()

    async def _notify_stream_event(self, request: ChatRequestRecord) -> None:
        if request.last_event_sequence < 0:
            return
        await self._notify_stream(
            tenant_id=request.tenant_id,
            request_id=request.request_id,
            sequence=request.last_event_sequence,
        )

    async def _notify_stream(
        self,
        *,
        tenant_id: UUID,
        request_id: UUID,
        sequence: int,
    ) -> None:
        if self._stream_notifier is None:
            return
        with suppress(Exception):
            await self._stream_notifier.publish(
                tenant_id=tenant_id,
                request_id=request_id,
                sequence=sequence,
            )

    def _require_submission_enabled(self) -> None:
        if not self._submission_enabled:
            raise ChatSubmissionDisabledError()

    @staticmethod
    def _summary_response(record: ConversationRecord) -> ConversationSummaryResponse:
        preview = ""
        for message in reversed(record.messages):
            if message.content:
                preview = message.content[:1000]
                break
        return ConversationSummaryResponse(
            conversation_id=str(record.conversation_id),
            product_model_id=record.product_model_id,
            title=record.title,
            preview=preview,
            updated_at=_as_utc(record.updated_at),
        )

    @staticmethod
    def _response(record: ConversationRecord) -> ConversationResponse:
        messages = [
            ConversationMessage(
                message_id=str(message.message_id),
                role="user" if message.role == "user" else "assistant",
                content=message.content,
                status=_public_message_status(message.status),
                created_at=_as_utc(message.created_at),
                request_id=str(message.request_id) if message.request_id else None,
            )
            for message in record.messages
            if message.role in {"user", "assistant"}
        ]
        return ConversationResponse(
            conversation_id=str(record.conversation_id),
            product_model_id=record.product_model_id,
            title=record.title,
            messages=messages,
            updated_at=_as_utc(record.updated_at),
            active_request_id=(
                str(record.active_request_id) if record.active_request_id else None
            ),
            active_request_cursor=record.active_request_cursor,
        )

    @staticmethod
    def _validate_event(
        row: StreamEventRecord,
        *,
        request_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        expected_sequence: int,
        require_started: bool,
        terminal: bool,
    ) -> dict[str, object]:
        if row.sequence != expected_sequence:
            raise ConversationInfrastructureError("STREAM_EVENT_SEQUENCE_INVALID")
        try:
            validated = _EVENT_ADAPTER.validate_python(row.event)
        except ValidationError:
            raise ConversationInfrastructureError("STREAM_EVENT_INVALID") from None
        event = cast(dict[str, object], validated.model_dump(mode="json"))
        if (
            event["request_id"] != str(request_id)
            or event["conversation_id"] != str(conversation_id)
            or event["message_id"] != str(message_id)
            or event["sequence"] != expected_sequence
        ):
            raise ConversationInfrastructureError("STREAM_EVENT_INVALID")
        if require_started and (event["type"] != "started" or expected_sequence != 0):
            raise ConversationInfrastructureError("STREAM_EVENT_SEQUENCE_INVALID")
        if not require_started and event["type"] == "started":
            raise ConversationInfrastructureError("STREAM_EVENT_SEQUENCE_INVALID")
        if terminal:
            raise ConversationInfrastructureError("STREAM_EVENT_AFTER_TERMINAL")
        if event["type"] == "failed":
            error = cast(Mapping[str, object], event["error"])
            if error["request_id"] != str(request_id):
                raise ConversationInfrastructureError("STREAM_EVENT_INVALID")
        return event


def _public_message_status(
    status: str,
) -> Literal["streaming", "complete", "stopped", "failed"]:
    if status in {"accepted", "completed"}:
        return "complete"
    if status == "streaming":
        return "streaming"
    if status == "stopped":
        return "stopped"
    return "failed"


def _as_utc(value: datetime) -> datetime:
    from datetime import UTC

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["ConversationService", "canonical_request_hash"]
