"""Consume fenced chat deliveries from RabbitMQ and execute durable requests."""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import suppress
from pathlib import Path
from uuid import UUID

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import select

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.conversations.billing_adapter import PromotionalChatBillingAdapter
from app.conversations.execution_repository import SqlAlchemyChatExecutionRepository
from app.conversations.ports import ChatRequestRecord
from app.conversations.readiness import clear_chat_worker_ready, mark_chat_worker_ready
from app.conversations.worker import ChatWorkerDependencies, DurableChatWorker
from app.core.settings import settings
from app.infrastructure.concurrency import (
    ConcurrencySaturated,
    ConcurrencyUnavailable,
    RedisLeaseSemaphore,
)
from app.infrastructure.database import dispose_engine, session_factory
from app.infrastructure.models import InferenceRequests, OutboxEvents
from app.infrastructure.redis import RedisChatStreamNotifier, dispose_redis, redis_client
from app.messaging.rabbitmq import (
    CHAT_ROUTING_KEY,
    EventEnvelope,
    RabbitMQPublisher,
)
from app.observability.logging import configure_logging
from app.observability.server import start_internal_metrics_server, stop_internal_metrics_server
from app.outbox.types import DELIVERABLE_OUTBOX_STATUSES
from app.providers.dashscope import DashScopeProvider


async def _heartbeat(worker_id: str, stopped: asyncio.Event) -> None:
    while not stopped.is_set():
        await mark_chat_worker_ready(worker_id=worker_id)
        try:
            await asyncio.wait_for(stopped.wait(), timeout=5.0)
        except TimeoutError:
            continue


async def _reconcile_settlements(
    billing: PromotionalChatBillingAdapter,
    repository: SqlAlchemyChatExecutionRepository,
    stopped: asyncio.Event,
) -> None:
    while not stopped.is_set():
        with suppress(Exception):
            await repository.reconcile_expired_once()
            await billing.reconcile_once()
        try:
            await asyncio.wait_for(stopped.wait(), timeout=5.0)
        except TimeoutError:
            continue


async def _request_for(envelope: EventEnvelope) -> ChatRequestRecord | None:
    if envelope.event_type != CHAT_ROUTING_KEY:
        raise ValueError("unsupported RabbitMQ event type")
    async with session_factory() as session:
        event = (
            await session.execute(
                select(OutboxEvents).where(
                    OutboxEvents.tenant_id == envelope.tenant_id,
                    OutboxEvents.id == envelope.event_id,
                    OutboxEvents.event_type == CHAT_ROUTING_KEY,
                    # A confirmed broker message can race ahead of the relay's
                    # separate fenced "published" mark transaction.
                    OutboxEvents.status.in_(DELIVERABLE_OUTBOX_STATUSES),
                )
            )
        ).scalar_one_or_none()
        if event is None or event.aggregate_version != envelope.aggregate_version:
            return None
        try:
            public_request_id = UUID(str(event.payload["request_id"]))
        except (KeyError, ValueError):
            raise ValueError("chat delivery request id is invalid") from None
        request = (
            await session.execute(
                select(InferenceRequests).where(
                    InferenceRequests.tenant_id == envelope.tenant_id,
                    InferenceRequests.request_id == public_request_id,
                    InferenceRequests.conversation_id == envelope.aggregate_id,
                )
            )
        ).scalar_one_or_none()
        if request is None:
            return None
        if request.conversation_id is None or request.message_id is None:
            raise ValueError("chat delivery request links are incomplete")
        if str(request.message_id) != str(event.payload.get("message_id")):
            raise ValueError("chat delivery message id does not match")
        return ChatRequestRecord(
            request_db_id=request.id,
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            tenant_id=request.tenant_id,
            status=request.status,
            last_event_sequence=int(request.last_event_sequence),
        )


async def _handle(message: AbstractIncomingMessage, worker: DurableChatWorker) -> None:
    try:
        envelope = EventEnvelope.from_body(message.body)
        request = await _request_for(envelope)
        if request is not None:
            await worker.process(request)
    except ConcurrencySaturated as error:
        await asyncio.sleep(min(error.retry_after_seconds, settings.concurrency_saturated_retry_delay_seconds))
        await message.nack(requeue=True)
        return
    except ConcurrencyUnavailable:
        await asyncio.sleep(settings.concurrency_saturated_retry_delay_seconds)
        await message.nack(requeue=True)
        return
    except ValueError:
        await message.reject(requeue=False)
        return
    except Exception:  # noqa: BLE001 - quorum delivery-limit bounds transient retries
        await message.nack(requeue=True)
        return
    await message.ack()


async def _run(args: argparse.Namespace) -> int:
    stopped = asyncio.Event()
    heartbeat: asyncio.Task[None] | None = None
    settlement_reconciler: asyncio.Task[None] | None = None
    metrics_server = None
    try:
        metrics_server = await start_internal_metrics_server()
        async with (
            RabbitMQPublisher(),
            DashScopeProvider.from_env() as provider,
        ):
            connection = await aio_pika.connect_robust(
                settings.rabbitmq_url.get_secret_value(),
                timeout=settings.rabbitmq_publish_timeout_seconds,
            )
            try:
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=1)
                queue = await channel.get_queue(settings.rabbitmq_chat_queue, ensure=True)
                billing = PromotionalChatBillingAdapter(session_factory)
                stream_notifier = RedisChatStreamNotifier(
                    redis_client,
                    environment=settings.app_environment,
                )
                repository = SqlAlchemyChatExecutionRepository(
                    session_factory,
                    stream_notifier=stream_notifier,
                )
                worker = DurableChatWorker(
                    ChatWorkerDependencies(
                        repository=repository,
                        text_generation=provider,
                        billing=billing,
                        concurrency=RedisLeaseSemaphore(
                            redis_client,
                            environment=settings.app_environment,
                        ),
                        concurrency_lease_seconds=settings.concurrency_lease_seconds,
                        concurrency_renewal_interval_seconds=(
                            settings.concurrency_renewal_interval_seconds
                        ),
                        concurrency_retry_delay_seconds=(
                            settings.concurrency_saturated_retry_delay_seconds
                        ),
                        stream_notifier=stream_notifier,
                        worker_id=args.worker_id,
                        lease_seconds=60,
                        max_completion_tokens=512,
                    )
                )
                await mark_chat_worker_ready(worker_id=args.worker_id)
                heartbeat = asyncio.create_task(_heartbeat(args.worker_id, stopped))
                settlement_reconciler = asyncio.create_task(
                    _reconcile_settlements(billing, repository, stopped)
                )
                if args.once:
                    message = await queue.get(timeout=args.timeout, fail=False)
                    if message is None:
                        return 3
                    await _handle(message, worker)
                    return 0
                async with queue.iterator() as iterator:
                    async for message in iterator:
                        await _handle(message, worker)
                return 0
            finally:
                await connection.close()
    finally:
        stopped.set()
        if heartbeat is not None:
            with suppress(Exception):
                await heartbeat
        if settlement_reconciler is not None:
            with suppress(Exception):
                await settlement_reconciler
        with suppress(Exception):
            await clear_chat_worker_ready(worker_id=args.worker_id)
        await stop_internal_metrics_server(metrics_server)
        await dispose_redis()
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--worker-id", default="local-chat-consumer")
    args = parser.parse_args(argv)
    configure_logging(service="mosaic-chat-worker", version=settings.app_version)
    if args.timeout <= 0:
        raise ValueError("timeout must be positive")
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
