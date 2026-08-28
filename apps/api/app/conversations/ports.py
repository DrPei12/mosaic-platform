"""Ports and immutable records for durable chat orchestration.

The HTTP process only accepts durable state transitions.  Provider calls,
queue publishing and streaming token production belong behind these ports and
are deliberately not implemented in this package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.providers.ports import Usage


@dataclass(frozen=True, slots=True)
class ConversationMessageRecord:
    message_id: UUID
    role: str
    content: str
    status: str
    created_at: datetime
    request_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    conversation_id: UUID
    tenant_id: UUID
    product_model_id: str
    title: str
    messages: tuple[ConversationMessageRecord, ...]
    updated_at: datetime
    active_request_id: UUID | None
    active_request_cursor: int | None = None


@dataclass(frozen=True, slots=True)
class ChatRequestRecord:
    request_db_id: UUID
    request_id: UUID
    conversation_id: UUID
    message_id: UUID
    tenant_id: UUID
    status: str = "queued"
    last_event_sequence: int = -1


@dataclass(frozen=True, slots=True)
class AcceptedChatRequest:
    request: ChatRequestRecord
    replayed: bool


@dataclass(frozen=True, slots=True)
class StopResult:
    request_id: UUID
    status: str
    changed: bool
    last_event_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class StreamEventRecord:
    sequence: int
    event: Mapping[str, object]


class ChatStreamSubscription(Protocol):
    """A best-effort wake-up subscription for one durable chat stream."""

    async def open(self) -> None: ...

    async def wait(self, timeout_seconds: float) -> bool: ...

    async def close(self) -> None: ...


class ChatStreamNotifier(Protocol):
    """Redis is a wake-up hint; the database remains the event source of truth."""

    def subscribe(
        self,
        *,
        tenant_id: UUID,
        request_id: UUID,
    ) -> ChatStreamSubscription: ...

    async def publish(
        self,
        *,
        tenant_id: UUID,
        request_id: UUID,
        sequence: int,
    ) -> None: ...


class ChatStreamPermit(Protocol):
    """A tenant and global stream lease held for one HTTP connection."""

    @property
    def lost(self) -> bool: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...


class ChatStreamAdmission(Protocol):
    async def acquire(self, *, tenant_id: UUID) -> ChatStreamPermit | None: ...


@dataclass(frozen=True, slots=True)
class ChatDeploymentRecord:
    """Trusted deployment snapshot loaded by the worker.

    Endpoint URLs, credentials and provider configuration are deliberately not
    part of this record.  A resolver composes the concrete
    :class:`TextGenerationPort` from the deployment id; tenant supplied data
    must never become a provider destination.
    """

    deployment_id: UUID
    product_model_id: str
    provider_model_id: str
    # Limit loaded with the claimed request's deployment row and passed
    # directly to runtime admission.
    concurrency_limit: int = 1
    routing_config: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatExecutionRecord:
    """Immutable worker input and the fenced lease snapshot.

    ``last_event_sequence`` is the last committed SSE sequence (0005 writes
    ``0`` for ``started``).  Every worker-side write must include
    ``lease_token`` and be checked against this snapshot by the repository.
    """

    request_db_id: UUID
    request_id: UUID
    conversation_id: UUID
    message_id: UUID
    tenant_id: UUID
    product_model_id: str
    deployment: ChatDeploymentRecord
    history: tuple[ConversationMessageRecord, ...]
    actor_user_id: UUID | None = None
    status: str = "running"
    last_event_sequence: int = 0
    worker_id: str | None = None
    lease_token: UUID | None = None
    lease_expires_at: datetime | None = None
    provider_request_id: str | None = None
    reservation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ChatUsageRecord:
    """Normalized usage persisted before financial settlement."""

    request_db_id: UUID
    request_id: UUID
    tenant_id: UUID
    deployment_id: UUID
    provider_request_id: str | None
    usage: Usage


@dataclass(frozen=True, slots=True)
class ChatLeaseCheck:
    """Result of a fenced read made between provider stream chunks."""

    lease_valid: bool
    stop_requested: bool = False


class ChatExecutionRepository(Protocol):
    """Short-transaction persistence boundary for the chat worker.

    Implementations must make each method one database transaction and fence
    every write by tenant, request id and lease token.  No method may keep a
    transaction open while the provider stream is being consumed.
    """

    async def claim_queued(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        tenant_id: UUID | None = None,
        request_id: UUID | None = None,
    ) -> ChatExecutionRecord | None: ...

    async def requeue_claimed(
        self,
        *,
        execution: ChatExecutionRecord,
    ) -> bool: ...

    async def check_lease_and_stop(
        self,
        *,
        execution: ChatExecutionRecord,
    ) -> ChatLeaseCheck: ...

    async def append_delta(
        self,
        *,
        execution: ChatExecutionRecord,
        expected_sequence: int,
        delta: str,
        provider_request_id: str | None,
    ) -> StreamEventRecord | None: ...

    async def mark_completed(
        self,
        *,
        execution: ChatExecutionRecord,
        expected_sequence: int,
        content: str,
        provider_request_id: str | None,
        usage: ChatUsageRecord,
    ) -> bool: ...

    async def mark_stopped(
        self,
        *,
        execution: ChatExecutionRecord,
        expected_sequence: int,
        content: str,
    ) -> bool: ...

    async def mark_failed(
        self,
        *,
        execution: ChatExecutionRecord,
        expected_sequence: int,
        error_code: str,
        error_details: Mapping[str, object] | None,
        provider_request_id: str | None,
    ) -> bool: ...

    async def mark_submitted_unknown(
        self,
        *,
        execution: ChatExecutionRecord,
        provider_request_id: str | None,
        error_code: str,
    ) -> bool: ...


class ChatBillingSettlementPort(Protocol):
    """Worker-side idempotent capture/release boundary.

    The hold is created by the HTTP acceptance transaction.  The worker never
    opens a reservation after provider work has started.
    """

    async def capture(
        self,
        *,
        execution: ChatExecutionRecord,
        usage: ChatUsageRecord,
    ) -> None: ...

    async def release(self, *, execution: ChatExecutionRecord) -> None: ...


class ConversationRepository(Protocol):
    async def list(
        self, *, tenant_id: UUID, actor_user_id: UUID, limit: int = 50
    ) -> Sequence[ConversationRecord]: ...

    async def get(
        self, *, tenant_id: UUID, actor_user_id: UUID, conversation_id: UUID
    ) -> ConversationRecord | None: ...

    async def create(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        product_model_id: str,
        client_request_id: str,
        request_hash: str,
    ) -> tuple[ConversationRecord, bool]: ...

    async def submit(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
        content: str,
        client_request_id: str,
        request_hash: str,
    ) -> AcceptedChatRequest: ...

    async def regenerate(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        client_request_id: str,
        request_hash: str,
    ) -> AcceptedChatRequest: ...

    async def stop(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
        request_id: UUID,
    ) -> StopResult: ...

    async def assert_request(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
        request_id: UUID,
    ) -> ChatRequestRecord: ...

    async def events(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        conversation_id: UUID,
        request_id: UUID,
        after_sequence: int,
    ) -> Sequence[StreamEventRecord]: ...


class ChatInferenceExecutorPort(Protocol):
    """Worker-owned provider boundary; never invoked from an API handler."""

    async def execute(self, *, request: ChatRequestRecord) -> None: ...


class ChatOutboxRelayPort(Protocol):
    """Durable outbox relay boundary; RabbitMQ/Celery is an integration concern."""

    async def publish(self, event: Mapping[str, object]) -> None: ...


__all__ = [
    "AcceptedChatRequest",
    "ChatBillingSettlementPort",
    "ChatDeploymentRecord",
    "ChatExecutionRecord",
    "ChatExecutionRepository",
    "ChatInferenceExecutorPort",
    "ChatLeaseCheck",
    "ChatOutboxRelayPort",
    "ChatRequestRecord",
    "ChatStreamAdmission",
    "ChatStreamNotifier",
    "ChatStreamPermit",
    "ChatStreamSubscription",
    "ChatUsageRecord",
    "ConversationMessageRecord",
    "ConversationRecord",
    "ConversationRepository",
    "StopResult",
    "StreamEventRecord",
]
