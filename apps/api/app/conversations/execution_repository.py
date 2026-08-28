"""PostgreSQL adapter for fenced, durable text-chat execution."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.ports import BillingUsage, PriceSnapshot
from app.billing.pricing import charge_for_usage, pricing_version
from app.conversations.ports import (
    ChatDeploymentRecord,
    ChatExecutionRecord,
    ChatExecutionRepository,
    ChatLeaseCheck,
    ChatStreamNotifier,
    ChatUsageRecord,
    ConversationMessageRecord,
    StreamEventRecord,
)
from app.infrastructure.models import (
        ChatStreamEvents,
        Conversations,
        InferenceRequests,
        Messages,
        ModelDeployments,
        PriceVersions,
        ProductModels,
        ProviderEndpoints,
        UsageRecords,
)

_RUNNING_STATUSES = frozenset({"running", "stop_requested"})
_TRUSTED_PROVIDER_NAME = "bailian"
_TRUSTED_PROTOCOL = "openai_compatible"
_TRUSTED_SECRET_REF = "env:DASHSCOPE_API_KEY"


class SqlAlchemyChatExecutionRepository(ChatExecutionRepository):
    """One short transaction per worker state transition."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        lease_extension_seconds: int = 60,
        stream_notifier: ChatStreamNotifier | None = None,
    ) -> None:
        if lease_extension_seconds < 1:
            raise ValueError("lease_extension_seconds must be positive")
        self._sessions = sessions
        self._lease_extension_seconds = lease_extension_seconds
        self._stream_notifier = stream_notifier

    async def claim_queued(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        tenant_id: uuid.UUID | None = None,
        request_id: uuid.UUID | None = None,
    ) -> ChatExecutionRecord | None:
        if not worker_id.strip() or len(worker_id) > 128:
            raise ValueError("worker_id must be 1 to 128 characters")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            predicates: list[Any] = [InferenceRequests.status == "queued"]
            if tenant_id is not None:
                predicates.append(InferenceRequests.tenant_id == tenant_id)
            if request_id is not None:
                predicates.append(InferenceRequests.request_id == request_id)
            row = (
                await session.execute(
                    select(
                        InferenceRequests,
                        Conversations,
                        ProductModels,
                        ModelDeployments,
                        ProviderEndpoints,
                    )
                    .join(
                        Conversations,
                        and_(
                            Conversations.tenant_id == InferenceRequests.tenant_id,
                            Conversations.id == InferenceRequests.conversation_id,
                        ),
                    )
                    .join(ProductModels, ProductModels.id == Conversations.product_model_id)
                    .join(
                        ModelDeployments,
                        ModelDeployments.id == InferenceRequests.model_deployment_id,
                    )
                    .join(
                        ProviderEndpoints,
                        ProviderEndpoints.id == ModelDeployments.provider_endpoint_id,
                    )
                    .where(
                        *predicates,
                        ProductModels.status == "active",
                        ProductModels.modality == "text",
                        ProductModels.task_type == "chat",
                        ModelDeployments.status == "active",
                        ProviderEndpoints.status == "active",
                        ProviderEndpoints.provider_name == _TRUSTED_PROVIDER_NAME,
                        ProviderEndpoints.protocol == _TRUSTED_PROTOCOL,
                        ProviderEndpoints.secret_ref == _TRUSTED_SECRET_REF,
                    )
                    .order_by(InferenceRequests.created_at, InferenceRequests.id)
                    .limit(1)
                    .with_for_update(of=InferenceRequests, skip_locked=True)
                )
            ).first()
            if row is None:
                return None
            request, conversation, product, deployment, _endpoint = row
            token = uuid.uuid4()
            request.status = "running"
            request.worker_id = worker_id.strip()
            request.lease_token = token
            request.lease_expires_at = now + timedelta(seconds=lease_seconds)
            request.last_heartbeat_at = now
            request.started_at = request.started_at or now
            request.updated_at = now
            await session.flush()
            history = await self._history(
                session,
                tenant_id=request.tenant_id,
                conversation_id=conversation.id,
            )
            if request.message_id is None or request.conversation_id is None:
                raise RuntimeError("claimed chat request is missing its durable message link")
            return ChatExecutionRecord(
                request_db_id=request.id,
                request_id=request.request_id,
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                tenant_id=request.tenant_id,
                product_model_id=product.model_key,
                deployment=ChatDeploymentRecord(
                    deployment_id=deployment.id,
                    product_model_id=product.model_key,
                    provider_model_id=deployment.provider_model_id,
                    concurrency_limit=int(deployment.concurrency_limit),
                    routing_config=dict(deployment.routing_config or {}),
                ),
                history=history,
                actor_user_id=request.actor_user_id,
                status="running",
                last_event_sequence=int(request.last_event_sequence),
                worker_id=request.worker_id,
                lease_token=token,
                lease_expires_at=request.lease_expires_at,
                provider_request_id=request.provider_request_id,
                reservation_id=request.billing_reservation_id,
            )

    async def requeue_claimed(self, *, execution: ChatExecutionRecord) -> bool:
        """Return a pre-provider claim to ``queued`` after permit saturation."""

        if execution.lease_token is None:
            return False
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                select(InferenceRequests)
                .where(
                    InferenceRequests.tenant_id == execution.tenant_id,
                    InferenceRequests.id == execution.request_db_id,
                    InferenceRequests.request_id == execution.request_id,
                    InferenceRequests.status == "running",
                    InferenceRequests.lease_token == execution.lease_token,
                )
                .with_for_update()
            )
            request = result.scalar_one_or_none()
            if request is None:
                return False
            request.status = "queued"
            request.worker_id = None
            request.lease_token = None
            request.lease_expires_at = None
            request.last_heartbeat_at = None
            request.updated_at = now
            return True

    async def check_lease_and_stop(
        self,
        *,
        execution: ChatExecutionRecord,
    ) -> ChatLeaseCheck:
        if execution.lease_token is None:
            return ChatLeaseCheck(lease_valid=False)
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            request = await self._locked_request(session, execution)
            if request is None or request.status not in _RUNNING_STATUSES:
                return ChatLeaseCheck(lease_valid=False)
            if request.lease_expires_at is None or _as_utc(request.lease_expires_at) <= now:
                return ChatLeaseCheck(lease_valid=False)
            request.last_heartbeat_at = now
            request.lease_expires_at = now + timedelta(seconds=self._lease_extension_seconds)
            request.updated_at = now
            return ChatLeaseCheck(
                lease_valid=True,
                stop_requested=request.status == "stop_requested",
            )

    async def append_delta(
        self,
        *,
        execution: ChatExecutionRecord,
        expected_sequence: int,
        delta: str,
        provider_request_id: str | None,
    ) -> StreamEventRecord | None:
        if not delta:
            raise ValueError("delta must not be empty")
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            request = await self._locked_writable_request(
                session,
                execution,
                expected_sequence=expected_sequence,
                statuses={"running"},
            )
            if request is None or not _provider_id_is_coherent(request, provider_request_id):
                return None
            message = await self._locked_message(session, execution)
            if message is None or message.status != "streaming":
                return None
            content = _text_content(message.content)
            message.content = {"type": "text", "text": f"{content}{delta}"}
            message.updated_at = now
            request.provider_request_id = provider_request_id or request.provider_request_id
            request.provider_started_at = request.provider_started_at or now
            request.last_event_sequence = expected_sequence
            request.last_heartbeat_at = now
            request.lease_expires_at = now + timedelta(seconds=self._lease_extension_seconds)
            request.updated_at = now
            payload: dict[str, object] = {
                "type": "delta",
                "request_id": str(request.request_id),
                "conversation_id": str(execution.conversation_id),
                "message_id": str(execution.message_id),
                "sequence": expected_sequence,
                "delta": delta,
            }
            session.add(_event(request, expected_sequence, "delta", payload, now))
            return StreamEventRecord(sequence=expected_sequence, event=payload)

    async def mark_completed(
        self,
        *,
        execution: ChatExecutionRecord,
        expected_sequence: int,
        content: str,
        provider_request_id: str | None,
        usage: ChatUsageRecord,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            request = await self._locked_writable_request(
                session,
                execution,
                expected_sequence=expected_sequence,
                statuses={"running"},
            )
            if request is None or not _provider_id_is_coherent(request, provider_request_id):
                return False
            message = await self._locked_message(session, execution)
            conversation = await self._locked_conversation(session, execution)
            if message is None or conversation is None:
                return False
            price = await _price_for_request(session, request)
            charge = charge_for_usage(
                price,
                BillingUsage(
                    input_tokens=usage.usage.prompt_tokens,
                    output_tokens=usage.usage.completion_tokens,
                    billable_units=usage.usage.total_tokens,
                ),
            )
            message.content = {"type": "text", "text": content}
            message.status = "completed"
            message.updated_at = now
            request.status = "succeeded"
            request.provider_request_id = provider_request_id or request.provider_request_id
            request.input_tokens = usage.usage.prompt_tokens
            request.output_tokens = usage.usage.completion_tokens
            request.last_event_sequence = expected_sequence
            request.completed_at = now
            request.terminal_reason = "provider_completed"
            request.lease_token = None
            request.lease_expires_at = None
            request.updated_at = now
            payload: dict[str, object] = {
                "type": "completed",
                "request_id": str(request.request_id),
                "conversation_id": str(execution.conversation_id),
                "message_id": str(execution.message_id),
                "sequence": expected_sequence,
                "content": content,
            }
            session.add(_event(request, expected_sequence, "completed", payload, now))
            await self._clear_active(conversation, request.id, now)
            existing_usage = (
                await session.execute(
                    select(UsageRecords.id).where(
                        UsageRecords.tenant_id == execution.tenant_id,
                        UsageRecords.inference_request_id == execution.request_db_id,
                    )
                )
            ).scalar_one_or_none()
            if existing_usage is None:
                session.add(
                    UsageRecords(
                        id=uuid.uuid4(),
                        tenant_id=execution.tenant_id,
                        actor_user_id=execution.actor_user_id,
                        inference_request_id=execution.request_db_id,
                        generation_job_id=None,
                        model_deployment_id=execution.deployment.deployment_id,
                        modality="text",
                        model_key=execution.product_model_id,
                        provider_request_id=provider_request_id,
                        provider_task_id=None,
                        pricing_version=pricing_version(price),
                        currency=price.currency,
                        input_tokens=usage.usage.prompt_tokens,
                        output_tokens=usage.usage.completion_tokens,
                        image_count=0,
                        video_seconds=0,
                        audio_seconds=0,
                        character_count=0,
                        audio_duration_ms=0,
                        video_duration_ms=0,
                        storage_bytes=0,
                        billable_units=usage.usage.total_tokens,
                        charge_amount_minor=charge.amount_minor,
                    )
                )
            return True

    async def mark_stopped(
        self,
        *,
        execution: ChatExecutionRecord,
        expected_sequence: int,
        content: str,
    ) -> bool:
        return await self._terminal_without_usage(
            execution=execution,
            expected_sequence=expected_sequence,
            content=content,
            event_type="stopped",
            request_status="stopped",
            message_status="stopped",
            error_code=None,
            error_details=None,
            provider_request_id=execution.provider_request_id,
        )

    async def mark_failed(
        self,
        *,
        execution: ChatExecutionRecord,
        expected_sequence: int,
        error_code: str,
        error_details: Mapping[str, object] | None,
        provider_request_id: str | None,
    ) -> bool:
        return await self._terminal_without_usage(
            execution=execution,
            expected_sequence=expected_sequence,
            content="",
            event_type="failed",
            request_status="failed",
            message_status="failed",
            error_code=error_code,
            error_details=error_details,
            provider_request_id=provider_request_id,
        )

    async def mark_submitted_unknown(
        self,
        *,
        execution: ChatExecutionRecord,
        provider_request_id: str | None,
        error_code: str,
    ) -> bool:
        return await self._terminal_without_usage(
            execution=execution,
            expected_sequence=execution.last_event_sequence + 1,
            content="",
            event_type="failed",
            request_status="submitted_unknown",
            message_status="failed",
            error_code=error_code,
            error_details={"code": error_code, "phase": "provider", "retryable": False},
            provider_request_id=provider_request_id,
            statuses={"running"},
            terminal_reason="provider_submission_unknown",
        )

    async def reconcile_expired_once(self, *, limit: int = 50) -> tuple[int, int]:
        """Move expired leases to explicit unknown or honor a durable stop."""

        if not 1 <= limit <= 500:
            raise ValueError("reconciliation limit must be between 1 and 500")
        now = datetime.now(UTC)
        unknown = 0
        stopped = 0
        notifications: list[tuple[uuid.UUID, uuid.UUID, int]] = []
        async with self._sessions() as session, session.begin():
            requests = tuple(
                (
                    await session.execute(
                        select(InferenceRequests)
                        .where(
                            InferenceRequests.status.in_(("running", "stop_requested")),
                            or_(
                                InferenceRequests.lease_expires_at.is_(None),
                                InferenceRequests.lease_expires_at <= now,
                            ),
                        )
                        .order_by(InferenceRequests.updated_at, InferenceRequests.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            )
            for request in requests:
                if request.status == "running":
                    if request.conversation_id is None or request.message_id is None:
                        continue
                    message = (
                        await session.execute(
                            select(Messages)
                            .where(
                                Messages.tenant_id == request.tenant_id,
                                Messages.id == request.message_id,
                                Messages.conversation_id == request.conversation_id,
                            )
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    conversation = (
                        await session.execute(
                            select(Conversations)
                            .where(
                                Conversations.tenant_id == request.tenant_id,
                                Conversations.id == request.conversation_id,
                                Conversations.active_inference_request_id == request.id,
                            )
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                    if message is None or conversation is None:
                        continue
                    sequence = int(request.last_event_sequence) + 1
                    error_code = "CHAT_LEASE_EXPIRED"
                    failed_payload: dict[str, object] = {
                        "type": "failed",
                        "request_id": str(request.request_id),
                        "conversation_id": str(request.conversation_id),
                        "message_id": str(request.message_id),
                        "sequence": sequence,
                        "error": {
                            "code": error_code,
                            "message": "模型响应未能完成",
                            "request_id": str(request.request_id),
                            "retryable": False,
                        },
                    }
                    session.add(_event(request, sequence, "failed", failed_payload, now))
                    message.status = "failed"
                    message.updated_at = now
                    request.status = "submitted_unknown"
                    request.error_code = error_code
                    request.sanitized_error_details = {
                        "code": error_code,
                        "phase": "lease",
                        "retryable": False,
                    }
                    request.terminal_reason = "worker_lease_expired_unknown"
                    request.last_event_sequence = sequence
                    request.completed_at = now
                    request.lease_token = None
                    request.lease_expires_at = None
                    request.updated_at = now
                    await self._clear_active(conversation, request.id, now)
                    unknown += 1
                    notifications.append((request.tenant_id, request.request_id, sequence))
                    continue
                if request.conversation_id is None or request.message_id is None:
                    continue
                message = (
                    await session.execute(
                        select(Messages)
                        .where(
                            Messages.tenant_id == request.tenant_id,
                            Messages.id == request.message_id,
                            Messages.conversation_id == request.conversation_id,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                conversation = (
                    await session.execute(
                        select(Conversations)
                        .where(
                            Conversations.tenant_id == request.tenant_id,
                            Conversations.id == request.conversation_id,
                            Conversations.active_inference_request_id == request.id,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if message is None or conversation is None:
                    continue
                sequence = int(request.last_event_sequence) + 1
                payload: dict[str, object] = {
                    "type": "stopped",
                    "request_id": str(request.request_id),
                    "conversation_id": str(request.conversation_id),
                    "message_id": str(request.message_id),
                    "sequence": sequence,
                }
                session.add(_event(request, sequence, "stopped", payload, now))
                message.status = "stopped"
                message.updated_at = now
                request.status = "stopped"
                request.last_event_sequence = sequence
                request.completed_at = now
                request.terminal_reason = "stop_reconciled_after_lease_expiry"
                request.lease_token = None
                request.lease_expires_at = None
                request.updated_at = now
                await self._clear_active(conversation, request.id, now)
                stopped += 1
                notifications.append((request.tenant_id, request.request_id, sequence))
        if self._stream_notifier is not None:
            for tenant_id, request_id, sequence in notifications:
                with suppress(Exception):
                    await self._stream_notifier.publish(
                        tenant_id=tenant_id,
                        request_id=request_id,
                        sequence=sequence,
                    )
        return unknown, stopped

    async def _terminal_without_usage(
        self,
        *,
        execution: ChatExecutionRecord,
        expected_sequence: int,
        content: str,
        event_type: str,
        request_status: str,
        message_status: str,
        error_code: str | None,
        error_details: Mapping[str, object] | None,
        provider_request_id: str | None,
        statuses: Sequence[str] | set[str] | frozenset[str] = _RUNNING_STATUSES,
        terminal_reason: str | None = None,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            request = await self._locked_writable_request(
                session,
                execution,
                expected_sequence=expected_sequence,
                statuses=statuses,
            )
            if request is None or not _provider_id_is_coherent(request, provider_request_id):
                return False
            message = await self._locked_message(session, execution)
            conversation = await self._locked_conversation(session, execution)
            if message is None or conversation is None:
                return False
            if content:
                message.content = {"type": "text", "text": content}
            message.status = message_status
            message.updated_at = now
            request.status = request_status
            request.provider_request_id = provider_request_id or request.provider_request_id
            request.error_code = error_code
            request.sanitized_error_details = _safe_details(error_details)
            request.last_event_sequence = expected_sequence
            request.completed_at = now
            request.terminal_reason = terminal_reason or event_type
            request.lease_token = None
            request.lease_expires_at = None
            request.updated_at = now
            payload: dict[str, object] = {
                "type": event_type,
                "request_id": str(request.request_id),
                "conversation_id": str(execution.conversation_id),
                "message_id": str(execution.message_id),
                "sequence": expected_sequence,
            }
            if event_type == "failed":
                payload["error"] = {
                    "code": error_code or "CHAT_PROVIDER_ERROR",
                    "message": "模型响应未能完成",
                    "request_id": str(request.request_id),
                    "retryable": bool((error_details or {}).get("retryable", False)),
                }
            session.add(_event(request, expected_sequence, event_type, payload, now))
            await self._clear_active(conversation, request.id, now)
            return True

    async def _locked_writable_request(
        self,
        session: AsyncSession,
        execution: ChatExecutionRecord,
        *,
        expected_sequence: int,
        statuses: Sequence[str] | set[str] | frozenset[str],
    ) -> InferenceRequests | None:
        request = await self._locked_request(session, execution)
        now = datetime.now(UTC)
        if (
            request is None
            or request.status not in statuses
            or request.last_event_sequence != expected_sequence - 1
            or request.lease_expires_at is None
            or _as_utc(request.lease_expires_at) <= now
        ):
            return None
        return request

    async def _locked_request(
        self,
        session: AsyncSession,
        execution: ChatExecutionRecord,
    ) -> InferenceRequests | None:
        if execution.lease_token is None:
            return None
        return (
            await session.execute(
                select(InferenceRequests)
                .where(
                    InferenceRequests.tenant_id == execution.tenant_id,
                    InferenceRequests.id == execution.request_db_id,
                    InferenceRequests.request_id == execution.request_id,
                    InferenceRequests.lease_token == execution.lease_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _locked_message(
        session: AsyncSession,
        execution: ChatExecutionRecord,
    ) -> Messages | None:
        return (
            await session.execute(
                select(Messages)
                .where(
                    Messages.tenant_id == execution.tenant_id,
                    Messages.conversation_id == execution.conversation_id,
                    Messages.id == execution.message_id,
                    Messages.request_id == execution.request_db_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _locked_conversation(
        session: AsyncSession,
        execution: ChatExecutionRecord,
    ) -> Conversations | None:
        return (
            await session.execute(
                select(Conversations)
                .where(
                    Conversations.tenant_id == execution.tenant_id,
                    Conversations.id == execution.conversation_id,
                    Conversations.active_inference_request_id == execution.request_db_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    @staticmethod
    async def _clear_active(
        conversation: Conversations,
        request_db_id: uuid.UUID,
        now: datetime,
    ) -> None:
        if conversation.active_inference_request_id != request_db_id:
            raise RuntimeError("conversation active request changed while terminalizing")
        conversation.active_inference_request_id = None
        conversation.version = int(conversation.version) + 1
        conversation.updated_at = now

    @staticmethod
    async def _history(
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> tuple[ConversationMessageRecord, ...]:
        rows = tuple(
            (
                await session.execute(
                    select(Messages)
                    .where(
                        Messages.tenant_id == tenant_id,
                        Messages.conversation_id == conversation_id,
                    )
                    .order_by(Messages.sequence_no)
                )
            ).scalars()
        )
        return tuple(
            ConversationMessageRecord(
                message_id=row.id,
                role=row.role,
                content=_text_content(row.content),
                status=row.status,
                created_at=_as_utc(row.created_at),
                request_id=None,
            )
            for row in rows
        )


async def _price_for_request(
    session: AsyncSession,
    request: InferenceRequests,
) -> PriceSnapshot:
    if request.accepted_price_version_id is None:
        raise RuntimeError("accepted chat request is missing its price snapshot")
    price = (
        await session.execute(
            select(PriceVersions).where(PriceVersions.id == request.accepted_price_version_id)
        )
    ).scalar_one_or_none()
    if price is None:
        raise RuntimeError("accepted chat price snapshot is missing")
    return PriceSnapshot(
        price_version_id=price.id,
        price_key=price.price_key,
        version=int(price.version),
        currency=price.currency,
        unit=price.unit,
        pricing=dict(price.pricing or {}),
    )


def _event(
    request: InferenceRequests,
    sequence: int,
    event_type: str,
    payload: Mapping[str, object],
    created_at: datetime,
) -> ChatStreamEvents:
    return ChatStreamEvents(
        id=uuid.uuid4(),
        tenant_id=request.tenant_id,
        inference_request_id=request.id,
        sequence_no=sequence,
        event_type=event_type,
        payload=dict(payload),
        created_at=created_at,
    )


def _provider_id_is_coherent(
    request: InferenceRequests,
    provider_request_id: str | None,
) -> bool:
    return (
        provider_request_id is None
        or request.provider_request_id is None
        or request.provider_request_id == provider_request_id
    )


def _text_content(value: object) -> str:
    if isinstance(value, Mapping):
        text = value.get("text")
        return text if isinstance(text, str) else ""
    return value if isinstance(value, str) else ""


def _safe_details(value: Mapping[str, object] | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        key: item
        for key in ("code", "phase", "retryable", "status_code", "request_id")
        if isinstance((item := value.get(key)), (str, bool, int)) or item is None
    }


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["SqlAlchemyChatExecutionRepository"]
