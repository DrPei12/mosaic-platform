from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.conversations import (
    chat_execution_stack_ready,
    get_conversation_service,
    router,
)
from app.api.exception_handlers import register_exception_handlers
from app.auth.dependencies import current_auth, require_authenticated_csrf
from app.contracts.conversation import ConversationResponse, ConversationSummaryResponse
from app.conversations.errors import ConversationNotFoundError, StreamCapacityError
from app.conversations.ports import AcceptedChatRequest, ChatRequestRecord, StopResult

TENANT_ID = UUID("00000000-0000-0000-0000-0000000000a1")
TENANT_B = UUID("00000000-0000-0000-0000-0000000000b1")
USER_ID = UUID("00000000-0000-0000-0000-0000000000a2")
USER_B = UUID("00000000-0000-0000-0000-0000000000b2")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-0000000000c1")
REQUEST_ID = UUID("00000000-0000-0000-0000-0000000000e1")
MESSAGE_ID = UUID("00000000-0000-0000-0000-0000000000d1")


class FakeService:
    def __init__(self) -> None:
        self.request = ChatRequestRecord(
            request_db_id=uuid4(),
            request_id=REQUEST_ID,
            conversation_id=CONVERSATION_ID,
            message_id=MESSAGE_ID,
            tenant_id=TENANT_ID,
        )
        self.actor_calls: list[tuple[str, UUID]] = []

    def _check_scope(self, name: str, kwargs: dict[str, object]) -> None:
        actor_user_id = kwargs["actor_user_id"]
        assert isinstance(actor_user_id, UUID)
        self.actor_calls.append((name, actor_user_id))
        if kwargs["tenant_id"] != TENANT_ID or actor_user_id != USER_ID:
            raise ConversationNotFoundError()

    @staticmethod
    def _response() -> ConversationResponse:
        return ConversationResponse(
            conversation_id=str(CONVERSATION_ID),
            product_model_id="qwen-3-5-plus",
            title="测试对话",
            messages=[],
            updated_at=datetime.now(UTC),
            active_request_id=None,
            active_request_cursor=None,
        )

    async def list(self, **kwargs):
        actor_user_id = kwargs["actor_user_id"]
        assert isinstance(actor_user_id, UUID)
        self.actor_calls.append(("list", actor_user_id))
        if kwargs["tenant_id"] != TENANT_ID or actor_user_id != USER_ID:
            return []
        return [
            ConversationSummaryResponse(
                conversation_id=str(CONVERSATION_ID),
                product_model_id="qwen-3-5-plus",
                title="测试对话",
                preview="",
                updated_at=datetime.now(UTC),
            )
        ]

    async def get(self, **kwargs):
        self._check_scope("get", kwargs)
        return self._response()

    async def create(self, **kwargs):
        self._check_scope("create", kwargs)
        return self._response()

    async def send(self, **kwargs):
        self._check_scope("send", kwargs)
        return AcceptedChatRequest(request=self.request, replayed=False)

    async def regenerate(self, **kwargs):
        self._check_scope("regenerate", kwargs)
        return AcceptedChatRequest(request=self.request, replayed=False)

    async def stop(self, **kwargs):
        self._check_scope("stop", kwargs)
        return StopResult(request_id=REQUEST_ID, status="succeeded", changed=False)

    async def assert_stream_request(self, **kwargs):
        self._check_scope("assert_stream_request", kwargs)
        return self.request

    async def stream(self, **kwargs):
        self._check_scope("events", kwargs)
        yield {
            "type": "started",
            "request_id": str(REQUEST_ID),
            "conversation_id": str(CONVERSATION_ID),
            "message_id": str(MESSAGE_ID),
            "sequence": 0,
        }
        yield {
            "type": "completed",
            "request_id": str(REQUEST_ID),
            "conversation_id": str(CONVERSATION_ID),
            "message_id": str(MESSAGE_ID),
            "sequence": 1,
            "content": "answer",
        }


class SaturatedService(FakeService):
    async def acquire_stream_admission(self, **kwargs):
        del kwargs
        raise StreamCapacityError()


def _app(
    *,
    service: FakeService | None = None,
    tenant_id: UUID = TENANT_ID,
    user_id: UUID = USER_ID,
) -> FastAPI:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(router)
    application.dependency_overrides[require_authenticated_csrf] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=tenant_id, user_id=user_id, role="member"),
    )
    application.dependency_overrides[current_auth] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=tenant_id, user_id=user_id, role="member"),
    )
    if service is not None:
        application.dependency_overrides[get_conversation_service] = lambda: service
    return application


@pytest.mark.asyncio
async def test_send_is_disabled_before_service_or_repository() -> None:
    app = _app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{CONVERSATION_ID}/messages",
            json={"content": "hello", "client_request_id": "send-1"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAT_SUBMISSION_DISABLED"


@pytest.mark.asyncio
async def test_feature_flag_alone_cannot_open_uncomposed_submission_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.conversations as conversations_module

    monkeypatch.setattr(conversations_module.settings, "chat_submission_enabled", True)
    app = _app(service=FakeService())
    app.dependency_overrides[chat_execution_stack_ready] = lambda: False
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{CONVERSATION_ID}/messages",
            json={"content": "hello", "client_request_id": "send-uncomposed"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAT_SUBMISSION_DISABLED"


@pytest.mark.asyncio
async def test_send_sse_contains_durable_id_and_business_request_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.conversations as conversations_module

    monkeypatch.setattr(conversations_module.settings, "chat_submission_enabled", True)
    app = _app(service=FakeService())
    app.dependency_overrides[chat_execution_stack_ready] = lambda: True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{CONVERSATION_ID}/messages",
            json={"content": "hello", "client_request_id": "send-1"},
        )
    assert response.status_code == 200
    assert response.headers["x-chat-request-id"] == str(REQUEST_ID)
    assert response.headers["x-message-id"] == str(MESSAGE_ID)
    assert "id: 0\ndata:" in response.text
    assert "id: 1\ndata:" in response.text


@pytest.mark.asyncio
async def test_stream_capacity_is_a_stable_429_before_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.conversations as conversations_module

    monkeypatch.setattr(conversations_module.settings, "chat_submission_enabled", True)
    app = _app(service=SaturatedService())
    app.dependency_overrides[chat_execution_stack_ready] = lambda: True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/v1/conversations/{CONVERSATION_ID}/messages",
            json={"content": "hello", "client_request_id": "send-capacity"},
        )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "STREAM_CAPACITY_EXCEEDED"
    assert response.json()["error"]["retryable"] is True


@pytest.mark.asyncio
async def test_resume_rejects_conflicting_header_and_query_cursor() -> None:
    service = FakeService()
    app = _app(service=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/requests/{REQUEST_ID}/resume",
            params={"cursor": "0"},
            headers={"Last-Event-ID": "1"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STREAM_CURSOR_INVALID"


@pytest.mark.asyncio
async def test_resume_rejects_negative_standard_last_event_id() -> None:
    app = _app(service=FakeService())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/requests/{REQUEST_ID}/resume",
            headers={"Last-Event-ID": "-1"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STREAM_CURSOR_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["succeeded", "submitted_unknown"])
async def test_resume_returns_204_when_cursor_already_covers_terminal_event(
    status: str,
) -> None:
    service = FakeService()
    service.request = ChatRequestRecord(
        request_db_id=service.request.request_db_id,
        request_id=REQUEST_ID,
        conversation_id=CONVERSATION_ID,
        message_id=MESSAGE_ID,
        tenant_id=TENANT_ID,
        status=status,
        last_event_sequence=1,
    )
    app = _app(service=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/requests/{REQUEST_ID}/resume",
            headers={"Last-Event-ID": "1"},
        )

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["x-chat-request-id"] == str(REQUEST_ID)


@pytest.mark.asyncio
async def test_resume_rejects_cursor_ahead_of_durable_request() -> None:
    service = FakeService()
    service.request = ChatRequestRecord(
        request_db_id=service.request.request_db_id,
        request_id=REQUEST_ID,
        conversation_id=CONVERSATION_ID,
        message_id=MESSAGE_ID,
        tenant_id=TENANT_ID,
        status="running",
        last_event_sequence=0,
    )
    app = _app(service=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/requests/{REQUEST_ID}/resume",
            headers={"Last-Event-ID": "1"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STREAM_CURSOR_INVALID"


@pytest.mark.asyncio
async def test_conversation_api_passes_auth_actor_through_every_public_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.conversations as conversations_module

    monkeypatch.setattr(conversations_module.settings, "chat_submission_enabled", True)
    service = FakeService()
    app = _app(service=service)
    app.dependency_overrides[chat_execution_stack_ready] = lambda: True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        responses = [
            await client.get("/api/v1/conversations"),
            await client.get(f"/api/v1/conversations/{CONVERSATION_ID}"),
            await client.post(
                "/api/v1/conversations",
                json={
                    "product_model_id": "qwen-3-5-plus",
                    "client_request_id": "create-1",
                },
            ),
            await client.post(
                f"/api/v1/conversations/{CONVERSATION_ID}/messages",
                json={"content": "hello", "client_request_id": "send-1"},
            ),
            await client.post(
                f"/api/v1/conversations/{CONVERSATION_ID}/messages/{MESSAGE_ID}/regenerate",
                json={"client_request_id": "regenerate-1"},
            ),
            await client.post(
                f"/api/v1/conversations/{CONVERSATION_ID}/requests/{REQUEST_ID}/stop",
            ),
            await client.get(
                f"/api/v1/conversations/{CONVERSATION_ID}/requests/{REQUEST_ID}/resume",
            ),
        ]

    assert [response.status_code for response in responses] == [200, 200, 201, 200, 200, 204, 200]
    assert {
        name
        for name, actor_user_id in service.actor_calls
        if actor_user_id == USER_ID
    } == {"list", "get", "create", "send", "regenerate", "stop", "assert_stream_request", "events"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tenant_id", "user_id"),
    [(TENANT_B, USER_ID), (TENANT_ID, USER_B)],
)
async def test_conversation_api_hides_cross_tenant_and_same_tenant_user_resources(
    monkeypatch: pytest.MonkeyPatch,
    tenant_id: UUID,
    user_id: UUID,
) -> None:
    import app.api.conversations as conversations_module

    monkeypatch.setattr(conversations_module.settings, "chat_submission_enabled", True)
    service = FakeService()
    app = _app(service=service, tenant_id=tenant_id, user_id=user_id)
    app.dependency_overrides[chat_execution_stack_ready] = lambda: True

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        listed = await client.get("/api/v1/conversations")
        fetched = await client.get(f"/api/v1/conversations/{CONVERSATION_ID}")
        submitted = await client.post(
            f"/api/v1/conversations/{CONVERSATION_ID}/messages",
            json={"content": "secret?", "client_request_id": "cross-send"},
        )
        regenerated = await client.post(
            f"/api/v1/conversations/{CONVERSATION_ID}/messages/{MESSAGE_ID}/regenerate",
            json={"client_request_id": "cross-regenerate"},
        )
        stopped = await client.post(
            f"/api/v1/conversations/{CONVERSATION_ID}/requests/{REQUEST_ID}/stop",
        )
        resumed = await client.get(
            f"/api/v1/conversations/{CONVERSATION_ID}/requests/{REQUEST_ID}/resume",
        )

    assert listed.status_code == 200
    assert listed.json() == []
    for response in (fetched, submitted, regenerated, stopped, resumed):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert "secret?" not in submitted.text
