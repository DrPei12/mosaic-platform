"""HTTP boundary for durable, tenant-scoped text conversations."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_csrf_permission, require_permission
from app.auth.repository import CurrentAuth
from app.billing.service import SqlAlchemyBillingService
from app.contracts.conversation import (
    ConversationResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    RegenerateMessageRequest,
    SendMessageRequest,
)
from app.conversations.errors import (
    ChatSubmissionDisabledError,
    ConversationInfrastructureError,
    StreamCursorError,
)
from app.conversations.ports import AcceptedChatRequest, ChatStreamPermit
from app.conversations.readiness import is_chat_worker_ready
from app.conversations.repository import SqlAlchemyConversationRepository
from app.conversations.service import ConversationService
from app.core.settings import settings
from app.infrastructure.concurrency import RedisChatStreamAdmission, RedisLeaseSemaphore
from app.infrastructure.database import get_db_session
from app.infrastructure.redis import RedisChatStreamNotifier, redis_client
from app.observability.metrics import set_sse_active

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])
require_conversation_permission = require_permission("conversation:use")
require_conversation_csrf_permission = require_csrf_permission("conversation:use")
_TERMINAL_REQUEST_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "stopped", "submitted_unknown"}
)


async def chat_execution_stack_ready() -> bool:
    """Require a live worker heartbeat, not only a feature flag."""

    return await is_chat_worker_ready()


def require_chat_submission_enabled(
    is_execution_stack_ready: Annotated[bool, Depends(chat_execution_stack_ready)],
) -> None:
    """Fail closed before the repository can create a queued request."""

    if not settings.chat_submission_enabled or not is_execution_stack_ready:
        raise ChatSubmissionDisabledError()


def get_conversation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationService:
    return ConversationService(
        SqlAlchemyConversationRepository(session, billing=SqlAlchemyBillingService(session)),
        submission_enabled=settings.chat_submission_enabled,
        stream_notifier=RedisChatStreamNotifier(
            redis_client,
            environment=settings.app_environment,
        ),
        stream_admission=RedisChatStreamAdmission(
            RedisLeaseSemaphore(redis_client, environment=settings.app_environment),
            tenant_limit=settings.chat_stream_tenant_limit,
            global_limit=settings.chat_stream_global_limit,
            ttl_seconds=settings.chat_stream_lease_seconds,
            renewal_interval_seconds=settings.chat_stream_renewal_interval_seconds,
        ),
        stream_max_duration_seconds=settings.chat_stream_max_duration_seconds,
        stream_replay_fallback_seconds=settings.chat_stream_replay_fallback_seconds,
    )


@router.get("", response_model=list[ConversationSummaryResponse])
async def list_conversations(
    response: Response,
    auth: Annotated[CurrentAuth, Depends(require_conversation_permission)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ConversationSummaryResponse]:
    response.headers["Cache-Control"] = "no-store"
    return await service.list(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        limit=limit,
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    response: Response,
    auth: Annotated[CurrentAuth, Depends(require_conversation_permission)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    response.headers["Cache-Control"] = "no-store"
    return await service.get(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        conversation_id=conversation_id,
    )


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: CreateConversationRequest,
    response: Response,
    auth: Annotated[CurrentAuth, Depends(require_conversation_csrf_permission)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    conversation = await service.create(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        request=payload,
    )
    response.headers["Location"] = f"/api/v1/conversations/{conversation.conversation_id}"
    response.headers["Cache-Control"] = "no-store"
    return conversation


@router.post(
    "/{conversation_id}/messages",
    response_class=StreamingResponse,
    response_model=None,
    dependencies=[Depends(require_chat_submission_enabled)],
)
async def send_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    auth: Annotated[CurrentAuth, Depends(require_conversation_csrf_permission)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> StreamingResponse:
    admission = await _acquire_stream_admission(service, tenant_id=auth.tenant_id)
    try:
        accepted = await service.send(
            tenant_id=auth.tenant_id,
            actor_user_id=auth.user_id,
            conversation_id=conversation_id,
            request=payload,
        )
    except BaseException:
        await _close_stream_admission(admission)
        raise
    return _stream_response(
        service=service,
        accepted=accepted,
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        conversation_id=conversation_id,
        admission=admission,
    )


@router.get(
    "/{conversation_id}/requests/{request_id}/resume",
    response_class=StreamingResponse,
    response_model=None,
    responses={204: {"description": "The supplied cursor already covers the terminal event."}},
)
async def resume_message(
    conversation_id: UUID,
    request_id: UUID,
    auth: Annotated[CurrentAuth, Depends(require_conversation_permission)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> StreamingResponse | Response:
    normalized_cursor = _resolve_cursor(last_event_id, cursor)
    request = await service.assert_stream_request(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        conversation_id=conversation_id,
        request_id=request_id,
    )
    if normalized_cursor is not None and normalized_cursor > request.last_event_sequence:
        raise StreamCursorError()
    if request.status in _TERMINAL_REQUEST_STATUSES:
        if request.last_event_sequence < 1:
            raise ConversationInfrastructureError("STREAM_TERMINAL_EVENT_MISSING")
        if normalized_cursor == request.last_event_sequence:
            return Response(
                status_code=204,
                headers={
                    "Cache-Control": "no-store",
                    "X-Chat-Request-ID": str(request.request_id),
                    "X-Message-ID": str(request.message_id),
                },
            )
    admission = await _acquire_stream_admission(service, tenant_id=auth.tenant_id)
    return _stream_response(
        service=service,
        accepted=AcceptedChatRequest(request=request, replayed=True),
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        conversation_id=conversation_id,
        cursor=normalized_cursor,
        admission=admission,
    )


@router.post(
    "/{conversation_id}/messages/{message_id}/regenerate",
    response_class=StreamingResponse,
    response_model=None,
    dependencies=[Depends(require_chat_submission_enabled)],
)
async def regenerate_message(
    conversation_id: UUID,
    message_id: UUID,
    payload: RegenerateMessageRequest,
    auth: Annotated[CurrentAuth, Depends(require_conversation_csrf_permission)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> StreamingResponse:
    admission = await _acquire_stream_admission(service, tenant_id=auth.tenant_id)
    try:
        accepted = await service.regenerate(
            tenant_id=auth.tenant_id,
            actor_user_id=auth.user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            request=payload,
        )
    except BaseException:
        await _close_stream_admission(admission)
        raise
    return _stream_response(
        service=service,
        accepted=accepted,
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        conversation_id=conversation_id,
        admission=admission,
    )


@router.post("/{conversation_id}/requests/{request_id}/stop", status_code=204)
async def stop_message(
    conversation_id: UUID,
    request_id: UUID,
    auth: Annotated[CurrentAuth, Depends(require_conversation_csrf_permission)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> Response:
    await service.stop(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        conversation_id=conversation_id,
        request_id=request_id,
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


async def _sse_body(
    service: ConversationService,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    conversation_id: UUID,
    request_id: UUID,
    cursor: int | None,
    admission: ChatStreamPermit | None = None,
) -> AsyncIterator[str]:
    set_sse_active(1)
    try:
        if admission is not None:
            await admission.start()
        async for event in service.stream(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            cursor=cursor,
            include_heartbeats=True,
        ):
            if admission is not None and admission.lost:
                return
            if event is None:
                yield ": heartbeat\n\n"
                continue
            sequence = event.get("sequence")
            if not isinstance(sequence, int) or sequence < 0:
                # The service validates this before yielding; keep the transport
                # fail-closed if a different event source is composed later.
                raise ConversationInfrastructureError("STREAM_EVENT_INVALID")
            yield (
                f"id: {sequence}\n"
                f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
            )
    finally:
        if admission is not None:
            await admission.close()
        set_sse_active(-1)


def _stream_response(
    *,
    service: ConversationService,
    accepted: AcceptedChatRequest,
    tenant_id: UUID,
    actor_user_id: UUID,
    conversation_id: UUID,
    cursor: int | None = None,
    admission: ChatStreamPermit | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        _sse_body(
            service,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            conversation_id=conversation_id,
            request_id=accepted.request.request_id,
            cursor=cursor,
            admission=admission,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Chat-Request-ID": str(accepted.request.request_id),
            "X-Message-ID": str(accepted.request.message_id),
        },
    )


async def _acquire_stream_admission(
    service: ConversationService,
    *,
    tenant_id: UUID,
) -> ChatStreamPermit | None:
    acquire = getattr(service, "acquire_stream_admission", None)
    if not callable(acquire):
        return None
    return await acquire(tenant_id=tenant_id)


async def _close_stream_admission(admission: ChatStreamPermit | None) -> None:
    if admission is not None:
        await admission.close()


def _parse_cursor(raw: str | None, *, minimum: int) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw, 10)
    except (TypeError, ValueError):
        raise StreamCursorError() from None
    if value < minimum:
        raise StreamCursorError()
    return value


def _resolve_cursor(last_event_id: str | None, cursor: str | None) -> int | None:
    header_cursor = _parse_cursor(last_event_id, minimum=0)
    query_cursor = _parse_cursor(cursor, minimum=-1)
    if (
        header_cursor is not None
        and query_cursor is not None
        and header_cursor != query_cursor
    ):
        raise StreamCursorError()
    return header_cursor if header_cursor is not None else query_cursor


__all__ = [
    "chat_execution_stack_ready",
    "create_conversation",
    "get_conversation",
    "get_conversation_service",
    "list_conversations",
    "regenerate_message",
    "require_chat_submission_enabled",
    "resume_message",
    "router",
    "send_message",
    "stop_message",
]
