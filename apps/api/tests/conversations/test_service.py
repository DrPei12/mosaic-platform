from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.contracts.conversation import RegenerateMessageRequest, SendMessageRequest
from app.conversations.errors import (
    ChatSubmissionDisabledError,
    ConversationBusyError,
    ConversationInfrastructureError,
    IdempotencyConflictError,
    StreamCursorError,
)
from app.conversations.ports import (
    AcceptedChatRequest,
    ChatRequestRecord,
    ConversationMessageRecord,
    ConversationRecord,
    ConversationRepository,
    StopResult,
    StreamEventRecord,
)
from app.conversations.service import ConversationService, canonical_request_hash

TENANT_A = UUID("00000000-0000-0000-0000-0000000000a1")
TENANT_B = UUID("00000000-0000-0000-0000-0000000000b1")
USER_A = UUID("00000000-0000-0000-0000-0000000000a2")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-0000000000c1")
MESSAGE_ID = UUID("00000000-0000-0000-0000-0000000000d1")


def _now() -> datetime:
    return datetime.now(UTC)


def _record(*, tenant_id: UUID = TENANT_A) -> ConversationRecord:
    return ConversationRecord(
        conversation_id=CONVERSATION_ID,
        tenant_id=tenant_id,
        product_model_id="qwen3.5-plus",
        title="测试对话",
        messages=(
            ConversationMessageRecord(
                message_id=MESSAGE_ID,
                role="assistant",
                content="answer",
                status="completed",
                created_at=_now(),
                request_id=UUID("00000000-0000-0000-0000-0000000000e1"),
            ),
        ),
        updated_at=_now(),
        active_request_id=None,
        active_request_cursor=None,
    )


def test_send_contract_rejects_whitespace_only_content_without_rewriting_valid_text() -> None:
    with pytest.raises(ValidationError):
        SendMessageRequest(content="  \r\n\t", client_request_id="send-blank")

    request = SendMessageRequest(content="  keep formatting  ", client_request_id="send-text")
    assert request.content == "  keep formatting  "


class FakeConversationRepository(ConversationRepository):
    def __init__(self) -> None:
        self.records = {TENANT_A: _record()}
        self.calls: list[str] = []
        self.active = False
        self.requests: dict[UUID, ChatRequestRecord] = {}
        self.events_by_request: dict[UUID, list[StreamEventRecord]] = {}
        self.stop_status = "succeeded"
        self.idempotency: dict[tuple[UUID, str, str], tuple[str, ChatRequestRecord]] = {}

    async def list(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        limit: int = 50,
    ) -> Sequence[ConversationRecord]:
        del actor_user_id
        record = self.records.get(tenant_id)
        return () if record is None else (record,)[:limit]

    async def get(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
    ) -> ConversationRecord | None:
        del actor_user_id
        record = self.records.get(tenant_id)
        return record if record and record.conversation_id == conversation_id else None

    async def create(self, **kwargs):
        self.calls.append("create")
        record = _record(tenant_id=kwargs["tenant_id"])
        self.records[kwargs["tenant_id"]] = record
        return record, False

    async def submit(self, **kwargs) -> AcceptedChatRequest:
        self.calls.append("submit")
        key = (kwargs["tenant_id"], "send", kwargs["client_request_id"])
        existing = self.idempotency.get(key)
        if existing:
            if existing[0] != kwargs["request_hash"]:
                raise IdempotencyConflictError()
            return AcceptedChatRequest(request=existing[1], replayed=True)
        if self.active:
            raise ConversationBusyError()
        request = ChatRequestRecord(
            request_db_id=uuid4(),
            request_id=UUID("00000000-0000-0000-0000-0000000000e1"),
            conversation_id=kwargs["conversation_id"],
            message_id=uuid4(),
            tenant_id=kwargs["tenant_id"],
            last_event_sequence=0,
        )
        self.idempotency[key] = (kwargs["request_hash"], request)
        self.requests[request.request_id] = request
        self.active = True
        self.events_by_request[request.request_id] = [
            StreamEventRecord(
                0,
                {
                    "type": "started",
                    "request_id": str(request.request_id),
                    "conversation_id": str(request.conversation_id),
                    "message_id": str(request.message_id),
                    "sequence": 0,
                },
            )
        ]
        return AcceptedChatRequest(request=request, replayed=False)

    async def regenerate(self, **kwargs) -> AcceptedChatRequest:
        self.calls.append("regenerate")
        request = ChatRequestRecord(
            request_db_id=uuid4(),
            request_id=uuid4(),
            conversation_id=kwargs["conversation_id"],
            message_id=kwargs["message_id"],
            tenant_id=kwargs["tenant_id"],
        )
        self.requests[request.request_id] = request
        return AcceptedChatRequest(request=request, replayed=False)

    async def stop(self, **kwargs) -> StopResult:
        self.calls.append("stop")
        return StopResult(
            request_id=kwargs["request_id"],
            status=self.stop_status,
            changed=False,
        )

    async def assert_request(self, **kwargs) -> ChatRequestRecord:
        request = self.requests[kwargs["request_id"]]
        assert request.tenant_id == kwargs["tenant_id"]
        assert request.conversation_id == kwargs["conversation_id"]
        return request

    async def events(self, **kwargs) -> Sequence[StreamEventRecord]:
        return tuple(
            row
            for row in self.events_by_request[kwargs["request_id"]]
            if row.sequence > kwargs["after_sequence"]
        )


@pytest.mark.asyncio
async def test_default_submission_is_fail_closed_before_repository_write() -> None:
    repository = FakeConversationRepository()
    service = ConversationService(repository)

    with pytest.raises(ChatSubmissionDisabledError):
        await service.send(
            tenant_id=TENANT_A,
            actor_user_id=USER_A,
            conversation_id=CONVERSATION_ID,
            request=SendMessageRequest(content="hello", client_request_id="send-1"),
        )

    assert repository.calls == []


@pytest.mark.asyncio
async def test_tenant_context_is_forwarded_and_same_key_is_replayable() -> None:
    repository = FakeConversationRepository()
    service = ConversationService(repository, submission_enabled=True)
    request = SendMessageRequest(content="hello", client_request_id="send-1")

    first = await service.send(
        tenant_id=TENANT_A,
        actor_user_id=USER_A,
        conversation_id=CONVERSATION_ID,
        request=request,
    )
    second = await service.send(
        tenant_id=TENANT_A,
        actor_user_id=USER_A,
        conversation_id=CONVERSATION_ID,
        request=request,
    )

    assert first.replayed is False
    assert second.replayed is True
    assert second.request.request_id == first.request.request_id
    with pytest.raises(IdempotencyConflictError):
        await service.send(
            tenant_id=TENANT_A,
            actor_user_id=USER_A,
            conversation_id=CONVERSATION_ID,
            request=SendMessageRequest(content="different", client_request_id="send-1"),
        )
    assert canonical_request_hash({"content": "hello"}) != canonical_request_hash({"content": "different"})


@pytest.mark.asyncio
async def test_stream_replays_cursor_plus_one_and_rejects_gaps() -> None:
    repository = FakeConversationRepository()
    service = ConversationService(
        repository,
        submission_enabled=True,
        stream_poll_deadline_seconds=0,
    )
    accepted = await service.send(
        tenant_id=TENANT_A,
        actor_user_id=USER_A,
        conversation_id=CONVERSATION_ID,
        request=SendMessageRequest(content="hello", client_request_id="send-1"),
    )
    repository.events_by_request[accepted.request.request_id].extend(
        [
            StreamEventRecord(
                1,
                {
                    "type": "completed",
                    "request_id": str(accepted.request.request_id),
                    "conversation_id": str(CONVERSATION_ID),
                    "message_id": str(accepted.request.message_id),
                    "sequence": 1,
                    "content": "answer",
                },
            )
        ]
    )
    events = [
        item
        async for item in service.stream(
            tenant_id=TENANT_A,
            actor_user_id=USER_A,
            conversation_id=CONVERSATION_ID,
            request_id=accepted.request.request_id,
            cursor=0,
        )
    ]
    assert [item["sequence"] for item in events] == [1]

    with pytest.raises(StreamCursorError):
        _ = [
            item
            async for item in service.stream(
                tenant_id=TENANT_A,
                actor_user_id=USER_A,
                conversation_id=CONVERSATION_ID,
                request_id=accepted.request.request_id,
                cursor=2,
            )
        ]

    repository.events_by_request[accepted.request.request_id] = [
        repository.events_by_request[accepted.request.request_id][0],
        StreamEventRecord(2, {**repository.events_by_request[accepted.request.request_id][1].event, "sequence": 2}),
    ]
    with pytest.raises(ConversationInfrastructureError):
        _ = [
            item
            async for item in service.stream(
                tenant_id=TENANT_A,
                actor_user_id=USER_A,
                conversation_id=CONVERSATION_ID,
                request_id=accepted.request.request_id,
            )
        ]


@pytest.mark.asyncio
async def test_stream_treats_submitted_unknown_as_terminal_after_failed_event() -> None:
    repository = FakeConversationRepository()
    service = ConversationService(
        repository,
        submission_enabled=True,
        stream_poll_deadline_seconds=0,
    )
    accepted = await service.send(
        tenant_id=TENANT_A,
        actor_user_id=USER_A,
        conversation_id=CONVERSATION_ID,
        request=SendMessageRequest(content="hello", client_request_id="send-unknown"),
    )
    request_id = accepted.request.request_id
    request = replace(
        accepted.request,
        status="submitted_unknown",
        last_event_sequence=1,
    )
    repository.requests[request_id] = request
    repository.events_by_request[request_id].append(
        StreamEventRecord(
            1,
            {
                "type": "failed",
                "request_id": str(request_id),
                "conversation_id": str(CONVERSATION_ID),
                "message_id": str(request.message_id),
                "sequence": 1,
                "error": {
                    "code": "CHAT_LEASE_EXPIRED",
                    "message": "模型响应未能完成",
                    "request_id": str(request_id),
                    "retryable": False,
                },
            },
        )
    )

    events = [
        item
        async for item in service.stream(
            tenant_id=TENANT_A,
            actor_user_id=USER_A,
            conversation_id=CONVERSATION_ID,
            request_id=request_id,
            cursor=0,
        )
    ]

    assert [item["type"] for item in events] == ["failed"]


@pytest.mark.asyncio
async def test_regenerate_reuses_assistant_message_and_stop_race_is_idempotent() -> None:
    repository = FakeConversationRepository()
    service = ConversationService(repository, submission_enabled=True)
    regenerated = await service.regenerate(
        tenant_id=TENANT_A,
        actor_user_id=USER_A,
        conversation_id=CONVERSATION_ID,
        message_id=MESSAGE_ID,
        request=RegenerateMessageRequest(client_request_id="regen-1"),
    )
    assert regenerated.request.message_id == MESSAGE_ID
    assert "submit" not in repository.calls

    stopped = await service.stop(
        tenant_id=TENANT_A,
        actor_user_id=USER_A,
        conversation_id=CONVERSATION_ID,
        request_id=regenerated.request.request_id,
    )
    assert stopped.changed is False
    assert stopped.status == "succeeded"
