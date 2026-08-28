"""Consume generation outbox deliveries from the durable RabbitMQ queue."""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import suppress
from pathlib import Path

import aio_pika
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import select

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import settings
from app.generations.executor import DashScopeGenerationExecutor
from app.generations.readiness import (
    GenerationWorkerKind,
    clear_generation_worker_ready,
    mark_generation_worker_ready,
)
from app.generations.recovery import GenerationRecoveryService, GenerationVideoRecoveryWorker
from app.generations.repository import OutboxRecord, SqlAlchemyGenerationRepository
from app.generations.resolver import SqlAlchemyDashScopeProviderResolver
from app.generations.storage import build_artifact_storage
from app.generations.worker import (
    DurableGenerationWorker,
    SqlAlchemyGenerationBilling,
    SqlAlchemyGenerationHeartbeat,
    WorkerDependencies,
)
from app.infrastructure.concurrency import (
    ConcurrencySaturated,
    ConcurrencyUnavailable,
    RedisLeaseSemaphore,
)
from app.infrastructure.database import dispose_engine, session_factory
from app.infrastructure.models import OutboxEvents
from app.infrastructure.redis import dispose_redis, redis_client
from app.messaging.rabbitmq import (
    GENERATION_ROUTING_KEY,
    VIDEO_GENERATION_ROUTING_KEY,
    EventEnvelope,
    RabbitMQPublisher,
    routing_key_for_outbox_event,
)
from app.observability.logging import configure_logging
from app.observability.server import start_internal_metrics_server, stop_internal_metrics_server
from app.outbox.types import DELIVERABLE_OUTBOX_STATUSES


async def _heartbeat(
    worker_id: str,
    stopped: asyncio.Event,
    *,
    worker_kind: GenerationWorkerKind,
) -> None:
    while not stopped.is_set():
        await mark_generation_worker_ready(worker_id=worker_id, worker_kind=worker_kind)
        try:
            await asyncio.wait_for(stopped.wait(), timeout=5.0)
        except TimeoutError:
            continue


async def _reconcile(
    billing: SqlAlchemyGenerationBilling,
    job_heartbeat: SqlAlchemyGenerationHeartbeat,
    video_recovery: GenerationVideoRecoveryWorker | None,
    stopped: asyncio.Event,
) -> None:
    while not stopped.is_set():
        with suppress(Exception):
            await job_heartbeat.reconcile_stalled_once()
            await billing.reconcile_once()
            if video_recovery is not None:
                await video_recovery.run_once()
        try:
            await asyncio.wait_for(stopped.wait(), timeout=30.0)
        except TimeoutError:
            continue


async def _event_for(
    envelope: EventEnvelope,
    *,
    expected_routing_key: str,
) -> OutboxRecord | None:
    if envelope.event_type != GENERATION_ROUTING_KEY:
        raise ValueError("unsupported generation event type")
    async with session_factory() as session:
        event = (
            await session.execute(
                select(OutboxEvents).where(
                    OutboxEvents.tenant_id == envelope.tenant_id,
                    OutboxEvents.id == envelope.event_id,
                    OutboxEvents.event_type == GENERATION_ROUTING_KEY,
                    # Broker confirm precedes the relay's separate published
                    # mark transaction, so pending is a valid short-lived race.
                    OutboxEvents.status.in_(DELIVERABLE_OUTBOX_STATUSES),
                )
            )
        ).scalar_one_or_none()
    if event is None or event.aggregate_version != envelope.aggregate_version:
        return None
    if routing_key_for_outbox_event(event.event_type, dict(event.payload or {})) != expected_routing_key:
        raise ValueError("generation delivery landed on the wrong queue")
    return OutboxRecord(
        event_id=event.id,
        tenant_id=event.tenant_id,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        event_type=event.event_type,
        aggregate_version=event.aggregate_version,
        payload=dict(event.payload or {}),
        attempts=int(event.attempts),
    )


async def _handle(
    message: AbstractIncomingMessage,
    worker: DurableGenerationWorker,
    *,
    expected_routing_key: str,
) -> None:
    try:
        envelope = EventEnvelope.from_body(message.body)
        event = await _event_for(envelope, expected_routing_key=expected_routing_key)
        if event is not None:
            await worker.process(event)
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
    worker_kind: GenerationWorkerKind = "video" if args.queue == "video" else "media"
    heartbeat_task: asyncio.Task[None] | None = None
    reconciliation_task: asyncio.Task[None] | None = None
    metrics_server = None
    try:
        metrics_server = await start_internal_metrics_server()
        if args.queue == "video":
            queue_name = settings.rabbitmq_video_generation_queue
            expected_routing_key = VIDEO_GENERATION_ROUTING_KEY
        else:
            queue_name = settings.rabbitmq_generation_queue
            expected_routing_key = GENERATION_ROUTING_KEY
        async with (
            RabbitMQPublisher(),
            session_factory() as repository_session,
            session_factory() as recovery_repository_session,
        ):
            connection = await aio_pika.connect_robust(
                settings.rabbitmq_url.get_secret_value(),
                timeout=settings.rabbitmq_publish_timeout_seconds,
            )
            try:
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=1)
                queue = await channel.get_queue(queue_name, ensure=True)
                billing = SqlAlchemyGenerationBilling(session_factory)
                artifact_storage = build_artifact_storage(settings)
                provider_resolver = SqlAlchemyDashScopeProviderResolver(session_factory)
                job_heartbeat = SqlAlchemyGenerationHeartbeat(
                    session_factory,
                    lease_seconds=int(settings.concurrency_lease_seconds),
                )
                worker = DurableGenerationWorker(
                    SqlAlchemyGenerationRepository(repository_session),
                    WorkerDependencies(
                        provider_resolver=provider_resolver,
                        artifact_storage=artifact_storage,
                        billing=billing,
                        executor=DashScopeGenerationExecutor(),
                        heartbeat=job_heartbeat,
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
                        worker_id=args.worker_id,
                    ),
                )
                video_recovery = (
                    GenerationVideoRecoveryWorker(
                        repository=SqlAlchemyGenerationRepository(
                            recovery_repository_session
                        ),
                        provider_resolver=provider_resolver,
                        artifact_storage=artifact_storage,
                        billing=billing,
                        recovery=GenerationRecoveryService(session_factory),
                        worker_id=f"{args.worker_id}-reconciler",
                        lease_seconds=int(settings.concurrency_lease_seconds),
                    )
                    if args.queue == "video"
                    else None
                )
                await mark_generation_worker_ready(
                    worker_id=args.worker_id,
                    worker_kind=worker_kind,
                )
                heartbeat_task = asyncio.create_task(
                    _heartbeat(args.worker_id, stopped, worker_kind=worker_kind)
                )
                reconciliation_task = asyncio.create_task(
                    _reconcile(billing, job_heartbeat, video_recovery, stopped)
                )
                if args.once:
                    message = await queue.get(timeout=args.timeout, fail=False)
                    if message is None:
                        return 3
                    await _handle(
                        message,
                        worker,
                        expected_routing_key=expected_routing_key,
                    )
                    return 0
                async with queue.iterator() as iterator:
                    async for message in iterator:
                        await _handle(
                            message,
                            worker,
                            expected_routing_key=expected_routing_key,
                        )
                return 0
            finally:
                await connection.close()
    finally:
        stopped.set()
        if heartbeat_task is not None:
            with suppress(Exception):
                await heartbeat_task
        if reconciliation_task is not None:
            with suppress(Exception):
                await reconciliation_task
        with suppress(Exception):
            await clear_generation_worker_ready(
                worker_id=args.worker_id,
                worker_kind=worker_kind,
            )
        await stop_internal_metrics_server(metrics_server)
        await dispose_redis()
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--queue", choices=("media", "video"), default="media")
    parser.add_argument("--worker-id", default="local-generation-consumer")
    args = parser.parse_args(argv)
    configure_logging(service="mosaic-generation-worker", version=settings.app_version)
    if args.timeout <= 0:
        raise ValueError("timeout must be positive")
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
