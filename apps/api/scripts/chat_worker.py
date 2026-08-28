"""Run the standalone fenced PostgreSQL text-chat worker."""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import suppress
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.conversations.billing_adapter import PromotionalChatBillingAdapter
from app.conversations.execution_repository import SqlAlchemyChatExecutionRepository
from app.conversations.readiness import clear_chat_worker_ready, mark_chat_worker_ready
from app.conversations.worker import ChatWorkerDependencies, DurableChatWorker
from app.core.settings import settings
from app.infrastructure.concurrency import (
    ConcurrencySaturated,
    ConcurrencyUnavailable,
    RedisLeaseSemaphore,
)
from app.infrastructure.database import dispose_engine, session_factory
from app.infrastructure.redis import RedisChatStreamNotifier, dispose_redis, redis_client
from app.providers.dashscope import DashScopeProvider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the MOSAIC text chat worker")
    parser.add_argument("--once", action="store_true", help="claim at most one request and exit")
    parser.add_argument("--worker-id", default="local-chat-worker")
    parser.add_argument("--poll-interval", type=float, default=0.25)
    return parser


async def _heartbeat(worker_id: str, stopped: asyncio.Event) -> None:
    while not stopped.is_set():
        await mark_chat_worker_ready(worker_id=worker_id)
        try:
            await asyncio.wait_for(stopped.wait(), timeout=5.0)
        except TimeoutError:
            continue


async def _run(args: argparse.Namespace) -> int:
    if args.poll_interval <= 0:
        raise ValueError("poll interval must be positive")
    stream_notifier = RedisChatStreamNotifier(
        redis_client,
        environment=settings.app_environment,
    )
    repository = SqlAlchemyChatExecutionRepository(
        session_factory,
        stream_notifier=stream_notifier,
    )
    billing = PromotionalChatBillingAdapter(session_factory)
    stopped = asyncio.Event()
    heartbeat: asyncio.Task[None] | None = None
    try:
        async with DashScopeProvider.from_env() as provider:
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
            if args.once:
                try:
                    return 0 if await worker.run_once() else 3
                except (ConcurrencySaturated, ConcurrencyUnavailable):
                    return 4
            while True:
                try:
                    claimed = await worker.run_once()
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
        if heartbeat is not None:
            with suppress(Exception):
                await heartbeat
        with suppress(Exception):
            await clear_chat_worker_ready(worker_id=args.worker_id)
        await dispose_redis()
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(_run(_parser().parse_args(argv)))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
