"""PostgreSQL repository for durable conversations.

Every mutation below is one short database transaction.  Provider calls and
queue publishing are intentionally absent: the transaction only records an
outbox command that a separately composed worker may consume.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.ports import BillingAcceptancePort
from app.billing.service import SqlAlchemyBillingService
from app.catalog.repository import resolve_accepted_decision
from app.conversations.errors import (
    ConversationBusyError,
    ConversationInfrastructureError,
    ConversationNotFoundError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    MessageNotLatestError,
    ModelNotFoundError,
    ModelUnavailableError,
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
from app.infrastructure.models import (
    ChatStreamEvents,
    Conversations,
    IdempotencyRecords,
    InferenceRequests,
    Messages,
    ModelDeployments,
    OutboxEvents,
    ProductModels,
    ProviderEndpoints,
    TenantModelEntitlements,
)

_IDEMPOTENCY_OPERATION_CREATE = "conversation.create"
_IDEMPOTENCY_OPERATION_SEND = "conversation.send"
_IDEMPOTENCY_OPERATION_REGENERATE = "conversation.regenerate"
_TERMINAL_REQUEST_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "stopped"}
)
_CONVERSATION_LIST_DEFAULT_LIMIT = 50
_CONVERSATION_LIST_MAX_LIMIT = 100


class SqlAlchemyConversationRepository(ConversationRepository):
    """Tenant-filtered SQLAlchemy implementation."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        billing: BillingAcceptancePort | None = None,
    ) -> None:
        self._session = session
        self._billing = billing or SqlAlchemyBillingService(session)

    async def list(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        limit: int = _CONVERSATION_LIST_DEFAULT_LIMIT,
    ) -> Sequence[ConversationRecord]:
        if not 1 <= limit <= _CONVERSATION_LIST_MAX_LIMIT:
            raise ValueError("conversation list limit must be between 1 and 100")
        async with self._session.begin():
            rows = tuple(
                (
                    await self._session.execute(
                        self._conversation_query(
                            tenant_id=tenant_id,
                            actor_user_id=actor_user_id,
                        ).where(
                            Conversations.status == "active"
                        )
                        .order_by(Conversations.updated_at.desc(), Conversations.id)
                        .limit(limit)
                    )
                ).all()
            )
            if not rows:
                return ()

            conversation_ids = tuple(conversation.id for conversation, _product in rows)
            latest_message_rank = func.row_number().over(
                partition_by=Messages.conversation_id,
                order_by=(Messages.sequence_no.desc(), Messages.id.desc()),
            ).label("message_rank")
            latest_message_ids = (
                select(Messages.id.label("message_id"), latest_message_rank)
                .where(
                    Messages.tenant_id == tenant_id,
                    Messages.conversation_id.in_(conversation_ids),
                    Messages.role.in_(["user", "assistant"]),
                )
                .subquery()
            )
            message_rows = tuple(
                (
                    await self._session.execute(
                        select(Messages)
                        .join(
                            latest_message_ids,
                            latest_message_ids.c.message_id == Messages.id,
                        )
                        .where(
                            Messages.tenant_id == tenant_id,
                            latest_message_ids.c.message_rank == 1,
                        )
                        .order_by(Messages.conversation_id, Messages.sequence_no)
                    )
                ).scalars()
            )
            active_request_ids = tuple(
                active_request_id
                for conversation, _product in rows
                if (active_request_id := _active_request_id(conversation)) is not None
            )
            request_rows = tuple(
                (
                    await self._session.execute(
                        select(InferenceRequests)
                        .where(
                            InferenceRequests.tenant_id == tenant_id,
                            InferenceRequests.id.in_(active_request_ids),
                        )
                        .order_by(InferenceRequests.conversation_id)
                    )
                ).scalars()
            )
            messages_by_conversation: dict[uuid.UUID, list[Messages]] = {}
            for message in message_rows:
                messages_by_conversation.setdefault(message.conversation_id, []).append(message)
            requests_by_conversation: dict[uuid.UUID, list[InferenceRequests]] = {}
            for request in request_rows:
                if request.conversation_id is not None:
                    requests_by_conversation.setdefault(request.conversation_id, []).append(request)

            return tuple(
                self._materialize_loaded(
                    row,
                    tenant_id=tenant_id,
                    messages=messages_by_conversation.get(row[0].id, ()),
                    requests=requests_by_conversation.get(row[0].id, ()),
                )
                for row in rows
            )

    async def get(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> ConversationRecord | None:
        async with self._session.begin():
            row = (
                await self._session.execute(
                    self._conversation_query(
                        tenant_id=tenant_id,
                        actor_user_id=actor_user_id,
                    ).where(
                        Conversations.tenant_id == tenant_id,
                        Conversations.id == conversation_id,
                    )
                )
            ).first()
            return await self._materialize(row, tenant_id=tenant_id) if row else None

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        product_model_id: str,
        client_request_id: str,
        request_hash: str,
    ) -> tuple[ConversationRecord, bool]:
        async with self._session.begin():
            idem, inserted = await self._claim_idempotency(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                operation=_IDEMPOTENCY_OPERATION_CREATE,
                key=client_request_id,
                request_hash=request_hash,
            )
            if not inserted:
                if idem.resource_id is None:
                    raise IdempotencyInProgressError()
                row = await self._get_row_by_id(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    conversation_id=idem.resource_id,
                )
                if row is None:
                    raise ConversationInfrastructureError()
                return await self._materialize(row, tenant_id=tenant_id), True

            product = (
                await self._session.execute(
                    select(ProductModels)
                    .join(
                        TenantModelEntitlements,
                        and_(
                            TenantModelEntitlements.product_model_id == ProductModels.id,
                            TenantModelEntitlements.tenant_id == tenant_id,
                            TenantModelEntitlements.enabled.is_(True),
                        ),
                    )
                    .where(
                        ProductModels.model_key == product_model_id,
                        ProductModels.modality == "text",
                        ProductModels.task_type == "chat",
                        ProductModels.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if product is None:
                raise ModelNotFoundError()

            now = datetime.now(UTC)
            conversation = Conversations(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                created_by_user_id=actor_user_id,
                product_model_id=product.id,
                title=product.display_name[:240],
                status="active",
                metadata_json={},
                created_at=now,
                updated_at=now,
            )
            self._session.add(conversation)
            await self._session.flush()
            await self._complete_idempotency(
                tenant_id=tenant_id,
                idem_id=idem.id,
                response_status=201,
                resource_type="conversation",
                resource_id=conversation.id,
                response_body={"conversation_id": str(conversation.id)},
            )
            row = await self._get_row_by_id(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                conversation_id=conversation.id,
            )
            if row is None:
                raise ConversationInfrastructureError()
            return await self._materialize(row, tenant_id=tenant_id), False

    async def submit(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        client_request_id: str,
        request_hash: str,
    ) -> AcceptedChatRequest:
        async with self._session.begin():
            idem, inserted = await self._claim_idempotency(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                operation=_IDEMPOTENCY_OPERATION_SEND,
                key=client_request_id,
                request_hash=request_hash,
            )
            if not inserted:
                return await self._replay_request(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    idem=idem,
                )

            conversation = await self._lock_conversation(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                conversation_id=conversation_id,
            )
            if conversation is None:
                raise ConversationNotFoundError()
            if _active_request_id(conversation) is not None:
                raise ConversationBusyError()
            route = await self._resolve_route(
                tenant_id=tenant_id,
                product_model_db_id=conversation.product_model_id,
            )
            request = await self._append_request_transaction(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                conversation=conversation,
                route=route,
                user_content=content,
                assistant_message_id=None,
                request_hash=request_hash,
                parent_request_id=None,
            )
            await self._complete_idempotency(
                tenant_id=tenant_id,
                idem_id=idem.id,
                response_status=202,
                resource_type="inference_request",
                resource_id=request.request_db_id,
                response_body={
                    "request_id": str(request.request_id),
                    "message_id": str(request.message_id),
                    "conversation_id": str(conversation.id),
                },
            )
            return AcceptedChatRequest(request=request, replayed=False)

    async def regenerate(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        client_request_id: str,
        request_hash: str,
    ) -> AcceptedChatRequest:
        async with self._session.begin():
            idem, inserted = await self._claim_idempotency(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                operation=_IDEMPOTENCY_OPERATION_REGENERATE,
                key=client_request_id,
                request_hash=request_hash,
            )
            if not inserted:
                return await self._replay_request(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    idem=idem,
                )

            conversation = await self._lock_conversation(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                conversation_id=conversation_id,
            )
            if conversation is None:
                raise ConversationNotFoundError()
            if _active_request_id(conversation) is not None:
                raise ConversationBusyError()
            target = (
                await self._session.execute(
                    select(Messages)
                    .where(
                        Messages.tenant_id == tenant_id,
                        Messages.conversation_id == conversation_id,
                        Messages.id == message_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if target is None:
                raise MessageNotLatestError()
            latest = (
                await self._session.execute(
                    select(Messages)
                    .where(
                        Messages.tenant_id == tenant_id,
                        Messages.conversation_id == conversation_id,
                    )
                    .order_by(Messages.sequence_no.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest is None or latest.id != target.id or target.role != "assistant":
                raise MessageNotLatestError()

            route = await self._resolve_route(
                tenant_id=tenant_id,
                product_model_db_id=conversation.product_model_id,
            )
            now = datetime.now(UTC)
            parent_request_id = target.request_id
            target.status = "streaming"
            target.content = {"type": "text", "text": ""}
            target.updated_at = now
            request = await self._append_request_transaction(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                conversation=conversation,
                route=route,
                user_content=None,
                assistant_message_id=target.id,
                request_hash=request_hash,
                parent_request_id=parent_request_id,
            )
            await self._complete_idempotency(
                tenant_id=tenant_id,
                idem_id=idem.id,
                response_status=202,
                resource_type="inference_request",
                resource_id=request.request_db_id,
                response_body={
                    "request_id": str(request.request_id),
                    "message_id": str(request.message_id),
                    "conversation_id": str(conversation.id),
                },
            )
            return AcceptedChatRequest(request=request, replayed=False)

    async def stop(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        request_id: uuid.UUID,
    ) -> StopResult:
        async with self._session.begin():
            conversation = await self._lock_conversation(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                conversation_id=conversation_id,
            )
            if conversation is None:
                raise ConversationNotFoundError()
            request = (
                await self._session.execute(
                    select(InferenceRequests)
                    .where(
                        InferenceRequests.tenant_id == tenant_id,
                        InferenceRequests.actor_user_id == actor_user_id,
                        InferenceRequests.conversation_id == conversation_id,
                        InferenceRequests.request_id == request_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if request is None:
                raise ConversationNotFoundError()

            active_db_id = _active_request_id(conversation)
            status = request.status
            if status in _TERMINAL_REQUEST_STATUSES:
                if active_db_id == request.id:
                    await self._clear_active(
                        tenant_id=tenant_id,
                        conversation=conversation,
                        request_db_id=request.id,
                    )
                return StopResult(
                    request_id=request_id,
                    status=status,
                    changed=False,
                    last_event_sequence=int(request.last_event_sequence),
                )
            if active_db_id != request.id:
                raise ConversationBusyError()

            now = datetime.now(UTC)
            if status == "queued":
                request.status = "stopped"
                request.completed_at = now
                request.updated_at = now
                message = await self._message_for_request(
                    tenant_id=tenant_id,
                    request=request,
                    lock=True,
                )
                if message is not None and message.status == "streaming":
                    message.status = "stopped"
                    message.updated_at = now
                await self._append_terminal_event(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    request=request,
                    event_type="stopped",
                )
                await self._clear_active(
                    tenant_id=tenant_id,
                    conversation=conversation,
                    request_db_id=request.id,
                )
                return StopResult(
                    request_id=request_id,
                    status="stopped",
                    changed=True,
                    last_event_sequence=int(request.last_event_sequence),
                )

            # A running provider call is cancelled by the worker.  Recording a
            # stop intent here is durable; this transaction never touches a
            # provider connection and never fabricates a terminal event.
            if status in {"running", "submitted_unknown", "stop_requested"}:
                request.status = "stop_requested"
                request.cancel_requested_at = now
                request.updated_at = now
                return StopResult(
                    request_id=request_id,
                    status="stop_requested",
                    changed=True,
                    last_event_sequence=int(request.last_event_sequence),
                )
            raise ConversationInfrastructureError("INFERENCE_STATE_INVALID")

    async def assert_request(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        request_id: uuid.UUID,
    ) -> ChatRequestRecord:
        async with self._session.begin():
            request = (
                await self._session.execute(
                    select(InferenceRequests)
                    .join(
                        Conversations,
                        and_(
                            Conversations.tenant_id == InferenceRequests.tenant_id,
                            Conversations.id == InferenceRequests.conversation_id,
                        ),
                    )
                    .where(
                        InferenceRequests.tenant_id == tenant_id,
                        InferenceRequests.actor_user_id == actor_user_id,
                        InferenceRequests.conversation_id == conversation_id,
                        InferenceRequests.request_id == request_id,
                        Conversations.created_by_user_id == actor_user_id,
                    )
                )
            ).scalar_one_or_none()
            if request is None or request.message_id is None:
                raise ConversationNotFoundError()
            return _request_record(request)

    async def events(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        request_id: uuid.UUID,
        after_sequence: int,
    ) -> Sequence[StreamEventRecord]:
        async with self._session.begin():
            return await self._events_in_transaction(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                conversation_id=conversation_id,
                request_id=request_id,
                after_sequence=after_sequence,
            )

    async def _events_in_transaction(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        request_id: uuid.UUID,
        after_sequence: int,
    ) -> Sequence[StreamEventRecord]:
        request = (
            await self._session.execute(
                select(InferenceRequests.id)
                .join(
                    Conversations,
                    and_(
                        Conversations.tenant_id == InferenceRequests.tenant_id,
                        Conversations.id == InferenceRequests.conversation_id,
                    ),
                )
                .where(
                    InferenceRequests.tenant_id == tenant_id,
                    InferenceRequests.actor_user_id == actor_user_id,
                    InferenceRequests.conversation_id == conversation_id,
                    InferenceRequests.request_id == request_id,
                    Conversations.created_by_user_id == actor_user_id,
                )
            )
        ).scalar_one_or_none()
        if request is None:
            raise ConversationNotFoundError()
        sequence_attr = ChatStreamEvents.sequence_no
        conditions: list[Any] = [
            ChatStreamEvents.tenant_id == tenant_id,
            ChatStreamEvents.inference_request_id == request,
            sequence_attr > after_sequence,
        ]
        rows = (
            await self._session.execute(
                select(ChatStreamEvents)
                .where(*conditions)
                .order_by(sequence_attr)
            )
        ).scalars()
        return tuple(_stream_event_record(row) for row in rows)

    async def _append_request_transaction(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        conversation: Conversations,
        route: tuple[uuid.UUID, str],
        user_content: str | None,
        assistant_message_id: uuid.UUID | None,
        request_hash: str,
        parent_request_id: uuid.UUID | None,
    ) -> ChatRequestRecord:
        deployment_id, _product_model_key = route
        max_sequence = (
            await self._session.execute(
                select(func.coalesce(func.max(Messages.sequence_no), 0)).where(
                    Messages.tenant_id == tenant_id,
                    Messages.conversation_id == conversation.id,
                )
            )
        ).scalar_one()
        next_sequence = int(max_sequence) + 1
        if user_content is not None:
            user_message = Messages(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                sequence_no=next_sequence,
                role="user",
                content={"type": "text", "text": user_content},
                status="accepted",
                author_user_id=actor_user_id,
            )
            self._session.add(user_message)
            next_sequence += 1
        if assistant_message_id is None:
            assistant_message_id = uuid.uuid4()
            assistant_message = Messages(
                id=assistant_message_id,
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                sequence_no=next_sequence,
                role="assistant",
                content={"type": "text", "text": ""},
                status="streaming",
                author_user_id=None,
            )
            self._session.add(assistant_message)
        await self._session.flush()
        decision = await resolve_accepted_decision(
            self._session,
            product_model_id=conversation.product_model_id,
            model_deployment_id=deployment_id,
        )
        if decision is None:
            raise ModelUnavailableError()
        request = InferenceRequests(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            request_id=uuid.uuid4(),
            actor_user_id=actor_user_id,
            conversation_id=conversation.id,
            message_id=assistant_message_id,
            model_deployment_id=deployment_id,
            status="queued",
            request_hash=request_hash,
            input_tokens=0,
            output_tokens=0,
            parent_request_id=parent_request_id,
        )
        request.accepted_model_revision_id = decision.model_revision_id
        request.accepted_model_deployment_id = decision.model_deployment_id
        request.accepted_routing_policy_id = decision.routing_policy_id
        request.accepted_price_version_id = decision.price_version_id
        request.accepted_capability_schema_version = decision.capability_schema_version
        request.accepted_capability_schema_hash = decision.capability_schema_hash
        request.accepted_capability_schema = dict(decision.capability_schema)
        request.accepted_input_snapshot = {"content": user_content}
        self._session.add(request)
        await self._session.flush()
        reservation = await self._billing.reserve_in_transaction(
            tenant_id=tenant_id,
            source_type="chat_inference",
            source_id=request.id,
            price=decision.price,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        request.billing_reservation_id = reservation.reservation_id
        await self._session.flush()
        assistant_row: Messages | None = (
            await self._session.execute(
                select(Messages).where(
                    Messages.tenant_id == tenant_id,
                    Messages.id == assistant_message_id,
                    Messages.conversation_id == conversation.id,
                )
            )
        ).scalar_one_or_none()
        if assistant_row is None:
            raise ConversationInfrastructureError()
        assistant_row.request_id = request.id
        await self._session.flush()
        version = _active_version(conversation) + 1
        _set_active_request(conversation, request.id, version)
        conversation.updated_at = datetime.now(UTC)
        event = _started_event(
            request_id=request.request_id,
            conversation_id=conversation.id,
            message_id=assistant_message_id,
        )
        await self._append_event(
            tenant_id=tenant_id,
            request=request,
            event=event,
        )
        self._session.add(
            OutboxEvents(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="chat.inference.execute",
                aggregate_version=version,
                payload={
                    "request_id": str(request.request_id),
                    "conversation_id": str(conversation.id),
                    "message_id": str(assistant_message_id),
                    "model_deployment_id": str(deployment_id),
                    "reservation_id": str(reservation.reservation_id),
                },
                status="pending",
                attempts=0,
            )
        )
        await self._session.flush()
        return _request_record(request)

    async def _append_event(
        self,
        *,
        tenant_id: uuid.UUID,
        request: InferenceRequests,
        event: Mapping[str, object],
    ) -> None:
        sequence = int(cast(int, event["sequence"]))
        self._session.add(
            ChatStreamEvents(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                inference_request_id=request.id,
                sequence_no=sequence,
                event_type=cast(str, event["type"]),
                payload=dict(event),
                created_at=datetime.now(UTC),
            )
        )
        request.last_event_sequence = sequence
        await self._session.flush()

    async def _append_terminal_event(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        request: InferenceRequests,
        event_type: str,
    ) -> None:
        rows = await self._events_in_transaction(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            conversation_id=cast(uuid.UUID, request.conversation_id),
            request_id=request.request_id,
            after_sequence=-1,
        )
        if any(item.event["type"] in {"completed", "stopped", "failed"} for item in rows):
            return
        sequence = rows[-1].sequence + 1 if rows else 0
        if event_type != "stopped":
            raise ConversationInfrastructureError("STREAM_EVENT_INVALID")
        await self._append_event(
            tenant_id=tenant_id,
            request=request,
            event={
                "type": "stopped",
                "request_id": str(request.request_id),
                "conversation_id": str(request.conversation_id),
                "message_id": str(request.message_id),
                "sequence": sequence,
            },
        )

    async def _message_for_request(
        self,
        *,
        tenant_id: uuid.UUID,
        request: InferenceRequests,
        lock: bool,
    ) -> Messages | None:
        query = select(Messages).where(
            Messages.tenant_id == tenant_id,
            Messages.id == request.message_id,
            Messages.conversation_id == request.conversation_id,
        )
        if lock:
            query = query.with_for_update()
        return (await self._session.execute(query)).scalar_one_or_none()

    async def _clear_active(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation: Conversations,
        request_db_id: uuid.UUID,
    ) -> None:
        await _clear_active_on_row(
            self._session,
            tenant_id=tenant_id,
            conversation=conversation,
            request_db_id=request_db_id,
        )

    async def _replay_request(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        idem: IdempotencyRecords,
    ) -> AcceptedChatRequest:
        if idem.request_hash is None:
            raise ConversationInfrastructureError()
        if idem.resource_id is None:
            raise IdempotencyInProgressError()
        request = (
            await self._session.execute(
                select(InferenceRequests)
                .join(
                    Conversations,
                    and_(
                        Conversations.tenant_id == InferenceRequests.tenant_id,
                        Conversations.id == InferenceRequests.conversation_id,
                    ),
                )
                .where(
                    InferenceRequests.tenant_id == tenant_id,
                    InferenceRequests.id == idem.resource_id,
                    InferenceRequests.actor_user_id == actor_user_id,
                    Conversations.created_by_user_id == actor_user_id,
                )
            )
        ).scalar_one_or_none()
        if request is None or request.conversation_id is None or request.message_id is None:
            raise ConversationInfrastructureError()
        return AcceptedChatRequest(request=_request_record(request), replayed=True)

    async def _claim_idempotency(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        operation: str,
        key: str,
        request_hash: str,
    ) -> tuple[IdempotencyRecords, bool]:
        inserted = await self._session.execute(
            pg_insert(IdempotencyRecords)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                operation=operation,
                key=key,
                request_hash=request_hash,
                status="processing",
            )
            .on_conflict_do_nothing(
                index_elements=[
                    IdempotencyRecords.tenant_id,
                    IdempotencyRecords.actor_user_id,
                    IdempotencyRecords.operation,
                    IdempotencyRecords.key,
                ]
            )
            .returning(IdempotencyRecords.id)
        )
        inserted_id = inserted.scalar_one_or_none()
        if inserted_id is not None:
            inserted_record = (
                await self._session.execute(
                    select(IdempotencyRecords).where(
                        IdempotencyRecords.tenant_id == tenant_id,
                        IdempotencyRecords.id == inserted_id,
                    )
                )
            ).scalar_one()
            return inserted_record, True
        existing_record = (
            await self._session.execute(
                select(IdempotencyRecords)
                .where(
                    IdempotencyRecords.tenant_id == tenant_id,
                    IdempotencyRecords.actor_user_id == actor_user_id,
                    IdempotencyRecords.operation == operation,
                    IdempotencyRecords.key == key,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing_record is None:
            raise ConversationInfrastructureError()
        if existing_record.request_hash != request_hash:
            raise IdempotencyConflictError()
        return existing_record, False

    async def _complete_idempotency(
        self,
        *,
        tenant_id: uuid.UUID,
        idem_id: uuid.UUID,
        response_status: int,
        resource_type: str,
        resource_id: uuid.UUID,
        response_body: Mapping[str, object],
    ) -> None:
        await self._session.execute(
            update(IdempotencyRecords)
            .where(
                IdempotencyRecords.tenant_id == tenant_id,
                IdempotencyRecords.id == idem_id,
            )
            .values(
                status="completed",
                response_status=response_status,
                resource_type=resource_type,
                resource_id=resource_id,
                response_body=dict(response_body),
                updated_at=datetime.now(UTC),
            )
        )

    async def _resolve_route(
        self,
        *,
        tenant_id: uuid.UUID,
        product_model_db_id: uuid.UUID,
    ) -> tuple[uuid.UUID, str]:
        product = (
            await self._session.execute(
                select(ProductModels)
                .join(
                    TenantModelEntitlements,
                    and_(
                        TenantModelEntitlements.product_model_id == ProductModels.id,
                        TenantModelEntitlements.tenant_id == tenant_id,
                        TenantModelEntitlements.enabled.is_(True),
                    ),
                )
                .where(
                    ProductModels.id == product_model_db_id,
                    ProductModels.modality == "text",
                    ProductModels.task_type == "chat",
                    ProductModels.status == "active",
                )
            )
        ).scalar_one_or_none()
        if product is None:
            raise ModelNotFoundError()
        route = (
            await self._session.execute(
                select(ModelDeployments)
                .join(
                    ProviderEndpoints,
                    ProviderEndpoints.id == ModelDeployments.provider_endpoint_id,
                )
                .where(
                    ModelDeployments.product_model_id == product.id,
                    ModelDeployments.status == "active",
                    ProviderEndpoints.status == "active",
                )
                .order_by(ModelDeployments.priority, ModelDeployments.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if route is None:
            raise ModelUnavailableError()
        return route.id, product.model_key

    def _conversation_query(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
    ) -> Select[Any]:
        return select(Conversations, ProductModels).join(
            ProductModels,
            ProductModels.id == Conversations.product_model_id,
        ).where(
            Conversations.tenant_id == tenant_id,
            Conversations.created_by_user_id == actor_user_id,
        )

    async def _get_row_by_id(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        lock: bool = False,
    ) -> Any | None:
        query = self._conversation_query(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
        ).where(
            Conversations.id == conversation_id,
        )
        if lock:
            query = query.with_for_update()
        return (await self._session.execute(query)).first()

    async def _lock_conversation(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> Conversations | None:
        row = await self._get_row_by_id(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            conversation_id=conversation_id,
            lock=True,
        )
        return row[0] if row else None

    async def _materialize(self, row: Any, *, tenant_id: uuid.UUID) -> ConversationRecord:
        conversation, _product = row
        messages = tuple(
            (
                await self._session.execute(
                    select(Messages)
                    .where(
                        Messages.tenant_id == tenant_id,
                        Messages.conversation_id == conversation.id,
                        Messages.role.in_(["user", "assistant"]),
                    )
                    .order_by(Messages.sequence_no)
                )
            ).scalars()
        )
        requests = tuple(
            (
                await self._session.execute(
                    select(InferenceRequests)
                    .where(
                        InferenceRequests.tenant_id == tenant_id,
                        InferenceRequests.conversation_id == conversation.id,
                    )
                    .order_by(InferenceRequests.created_at.desc())
                )
            ).scalars()
        )
        return self._materialize_loaded(
            row,
            tenant_id=tenant_id,
            messages=messages,
            requests=requests,
        )

    def _materialize_loaded(
        self,
        row: Any,
        *,
        tenant_id: uuid.UUID,
        messages: Sequence[Messages],
        requests: Sequence[InferenceRequests],
    ) -> ConversationRecord:
        conversation, product = row
        latest_request_by_message: dict[uuid.UUID, uuid.UUID] = {}
        for request in requests:
            if request.message_id is not None:
                latest_request_by_message.setdefault(request.message_id, request.request_id)
        active = _active_request_id(conversation)
        active_public: uuid.UUID | None = None
        active_cursor: int | None = None
        if active is not None:
            active_request = next((item for item in requests if item.id == active), None)
            if active_request is None:
                raise ConversationInfrastructureError("CONVERSATION_STATE_INVALID")
            active_public = active_request.request_id
            active_cursor = int(active_request.last_event_sequence)
        return ConversationRecord(
            conversation_id=conversation.id,
            tenant_id=tenant_id,
            product_model_id=product.model_key,
            title=(conversation.title or product.display_name or "新对话")[:240],
            messages=tuple(
                ConversationMessageRecord(
                    message_id=message.id,
                    role=message.role,
                    content=_text_content(message.content),
                    status=message.status,
                    created_at=_as_utc(message.created_at),
                    request_id=latest_request_by_message.get(message.id),
                )
                for message in messages
            ),
            updated_at=_as_utc(conversation.updated_at),
            active_request_id=active_public,
            active_request_cursor=active_cursor,
        )


def _request_record(request: InferenceRequests) -> ChatRequestRecord:
    if request.conversation_id is None or request.message_id is None:
        raise ConversationInfrastructureError()
    return ChatRequestRecord(
        request_db_id=request.id,
        request_id=request.request_id,
        conversation_id=request.conversation_id,
        message_id=request.message_id,
        tenant_id=request.tenant_id,
        status=request.status,
        last_event_sequence=int(request.last_event_sequence),
    )


def _started_event(
    *,
    request_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
) -> Mapping[str, object]:
    return {
        "type": "started",
        "request_id": str(request_id),
        "conversation_id": str(conversation_id),
        "message_id": str(message_id),
        "sequence": 0,
    }


def _text_content(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        candidate = value.get("text")
        if isinstance(candidate, str):
            return candidate
    return ""


def _active_request_id(conversation: Conversations) -> uuid.UUID | None:
    value = conversation.active_inference_request_id
    return value if isinstance(value, uuid.UUID) else None


def _active_version(conversation: Conversations) -> int:
    return int(conversation.version)


def _set_active_request(
    conversation: Conversations,
    request_db_id: uuid.UUID,
    version: int,
) -> None:
    conversation.active_inference_request_id = request_db_id
    conversation.version = version


async def _clear_active_on_row(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    conversation: Conversations,
    request_db_id: uuid.UUID,
) -> None:
    previous_version = conversation.version
    conditions: list[Any] = [
        Conversations.tenant_id == tenant_id,
        Conversations.id == conversation.id,
        Conversations.active_inference_request_id == request_db_id,
        Conversations.version == previous_version,
    ]
    result = await session.execute(
        update(Conversations)
        .where(*conditions)
        .execution_options(synchronize_session=False)
        .values(
            active_inference_request_id=None,
            version=previous_version + 1,
            updated_at=datetime.now(UTC),
        )
    )
    if cast(Any, result).rowcount != 1:
        raise ConversationInfrastructureError("CONVERSATION_STATE_CONFLICT")
    conversation.active_inference_request_id = None
    conversation.version = previous_version + 1


def _stream_event_record(row: ChatStreamEvents) -> StreamEventRecord:
    payload = dict(row.payload)
    if payload.get("type") != row.event_type or payload.get("sequence") != row.sequence_no:
        raise ConversationInfrastructureError("STREAM_EVENT_INVALID")
    return StreamEventRecord(sequence=int(row.sequence_no), event=payload)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = ["SqlAlchemyConversationRepository"]
