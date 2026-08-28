from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.conversations.errors import ConversationInfrastructureError
from app.conversations.ports import ChatRequestRecord
from app.conversations.worker import ChatWorkerDependencies, DurableChatWorker


def _request() -> ChatRequestRecord:
    return ChatRequestRecord(
        request_db_id=uuid4(),
        request_id=uuid4(),
        conversation_id=uuid4(),
        message_id=uuid4(),
        tenant_id=UUID("00000000-0000-0000-0000-0000000000a1"),
    )


@pytest.mark.asyncio
async def test_chat_worker_fails_closed_without_composed_executor() -> None:
    worker = DurableChatWorker(ChatWorkerDependencies())

    with pytest.raises(ConversationInfrastructureError) as captured:
        await worker.process(_request())

    assert captured.value.code == "CHAT_WORKER_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_chat_worker_delegates_only_to_explicit_executor() -> None:
    calls: list[ChatRequestRecord] = []

    class RecordingExecutor:
        async def execute(self, *, request: ChatRequestRecord) -> None:
            calls.append(request)

    request = _request()
    worker = DurableChatWorker(ChatWorkerDependencies(executor=RecordingExecutor()))

    await worker.process(request)

    assert calls == [request]
