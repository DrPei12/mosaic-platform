"""Run the standalone real media-generation worker."""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import suppress
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts.generations import GenerationModality
from app.core.settings import settings
from app.generations.executor import DashScopeGenerationExecutor
from app.generations.readiness import (
    clear_generation_worker_ready,
    mark_generation_worker_ready,
)
from app.generations.recovery import GenerationRecoveryService, GenerationVideoRecoveryWorker
from app.generations.repository import SqlAlchemyGenerationRepository
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
from app.infrastructure.redis import dispose_redis, redis_client


async def _heartbeat(worker_id: str, stopped: asyncio.Event) -> None:
    while not stopped.is_set():
        await mark_generation_worker_ready(worker_id=worker_id)
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


async def _run(args: argparse.Namespace) -> int:
    if args.poll_interval <= 0:
        raise ValueError("poll interval must be positive")
    stopped = asyncio.Event()
    modalities: tuple[GenerationModality, ...] = (
        ("video",) if args.queue == "video" else ("text", "image", "audio")
    )
    heartbeat_task: asyncio.Task[None] | None = None
    reconciliation_task: asyncio.Task[None] | None = None
    try:
        async with (
            session_factory() as repository_session,
            session_factory() as recovery_repository_session,
        ):
            billing = SqlAlchemyGenerationBilling(session_factory)
            provider_resolver = SqlAlchemyDashScopeProviderResolver(session_factory)
            artifact_storage = build_artifact_storage(settings)
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
                    repository=SqlAlchemyGenerationRepository(recovery_repository_session),
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
            await mark_generation_worker_ready(worker_id=args.worker_id)
            heartbeat_task = asyncio.create_task(_heartbeat(args.worker_id, stopped))
            reconciliation_task = asyncio.create_task(
                _reconcile(billing, job_heartbeat, video_recovery, stopped)
            )
            if args.once:
                try:
                    return 0 if await worker.run_once(modalities=modalities) else 3
                except (ConcurrencySaturated, ConcurrencyUnavailable):
                    return 4
            while True:
                try:
                    claimed = await worker.run_once(modalities=modalities)
                except ConcurrencySaturated as error:
                    await asyncio.sleep(
                        min(
                            error.retry_after_seconds,
                            settings.concurrency_saturated_retry_delay_seconds,
                        )
                    )
                    continue
                except ConcurrencyUnavailable:
                    await asyncio.sleep(settings.concurrency_saturated_retry_delay_seconds)
                    continue
                if not claimed:
                    await asyncio.sleep(args.poll_interval)
    finally:
        stopped.set()
        if heartbeat_task is not None:
            with suppress(Exception):
                await heartbeat_task
        if reconciliation_task is not None:
            with suppress(Exception):
                await reconciliation_task
        with suppress(Exception):
            await clear_generation_worker_ready(worker_id=args.worker_id)
        await dispose_redis()
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--worker-id", default="local-generation-worker")
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--queue", choices=("media", "video"), default="media")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
