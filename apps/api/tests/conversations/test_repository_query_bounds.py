from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Self
from uuid import UUID

import pytest

from app.conversations.repository import SqlAlchemyConversationRepository

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
USER_ID = UUID("00000000-0000-0000-0000-000000000011")


class _Result:
    def __init__(
        self,
        *,
        rows: tuple[object, ...] = (),
        scalar_rows: tuple[object, ...] = (),
    ) -> None:
        self._rows = rows
        self._scalar_rows = scalar_rows

    def all(self) -> tuple[object, ...]:
        return self._rows

    def scalars(self) -> tuple[object, ...]:
        return self._scalar_rows


class _Transaction:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Session:
    def __init__(
        self,
        rows: tuple[tuple[object, object], ...],
        messages: tuple[object, ...],
        requests: tuple[object, ...],
        *,
        list_limit: int,
    ) -> None:
        self._rows = rows
        self._messages = messages
        self._requests = requests
        self._list_limit = list_limit
        self.statements: list[object] = []

    def begin(self) -> _Transaction:
        return _Transaction()

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _Result(rows=self._rows[: self._list_limit])
        if len(self.statements) == 2:
            return _Result(scalar_rows=self._messages)
        if len(self.statements) == 3:
            return _Result(scalar_rows=self._requests)
        raise AssertionError("conversation list issued an unexpected query")


def _fixture_rows(
    count: int,
) -> tuple[
    tuple[tuple[object, object], ...],
    tuple[object, ...],
    tuple[object, ...],
]:
    now = datetime(2026, 8, 26, tzinfo=UTC)
    rows: list[tuple[object, object]] = []
    messages: list[object] = []
    requests: list[object] = []
    for index in range(count):
        conversation_id = UUID(int=index + 1)
        message_id = UUID(int=10_000 + index)
        request_id = UUID(int=20_000 + index)
        request_db_id = UUID(int=30_000 + index)
        rows.append(
            (
                SimpleNamespace(
                    id=conversation_id,
                    created_by_user_id=USER_ID,
                    title=f"Conversation {index}",
                    updated_at=now,
                    active_inference_request_id=request_db_id,
                ),
                SimpleNamespace(model_key="qwen-3-5-plus", display_name="Qwen"),
            )
        )
        messages.append(
            SimpleNamespace(
                conversation_id=conversation_id,
                id=message_id,
                role="assistant",
                content={"type": "text", "text": f"answer-{index}"},
                status="completed",
                created_at=now,
            )
        )
        requests.append(
            SimpleNamespace(
                conversation_id=conversation_id,
                id=request_db_id,
                request_id=request_id,
                message_id=message_id,
                actor_user_id=USER_ID,
                created_at=now,
                last_event_sequence=1,
            )
        )
    return tuple(rows), tuple(messages), tuple(requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation_count", [1, 80])
async def test_conversation_list_uses_bounded_batch_queries(
    conversation_count: int,
) -> None:
    rows, messages, requests = _fixture_rows(conversation_count)
    session = _Session(rows, messages, requests, list_limit=10)

    records = await SqlAlchemyConversationRepository(session).list(
        tenant_id=TENANT_ID,
        actor_user_id=USER_ID,
        limit=10,
    )

    assert len(records) == min(conversation_count, 10)
    assert len(session.statements) == 3
    assert "limit" in str(session.statements[0]).lower()
    message_statement = str(session.statements[1]).lower()
    assert "row_number() over" in message_statement
    assert "partition by messages.conversation_id" in message_statement
    assert "message_rank" in message_statement
    assert "inference_requests.id in" in str(session.statements[2]).lower()
    assert "conversations.created_by_user_id" in str(session.statements[0]).lower()
    assert records[0].messages[0].content == "answer-0"
    assert records[0].messages[0].request_id == UUID(int=20_000)
    assert records[0].active_request_id == UUID(int=20_000)


@pytest.mark.asyncio
async def test_conversation_list_rejects_unbounded_limit() -> None:
    rows, messages, requests = _fixture_rows(1)
    session = _Session(rows, messages, requests, list_limit=1)

    with pytest.raises(ValueError, match="conversation list limit"):
        await SqlAlchemyConversationRepository(session).list(
            tenant_id=TENANT_ID,
            actor_user_id=USER_ID,
            limit=101,
        )
