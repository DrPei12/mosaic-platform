"""Run one fenced transactional-outbox relay batch."""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import suppress
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import settings
from app.infrastructure.database import dispose_engine, session_factory
from app.messaging.rabbitmq import CHAT_ROUTING_KEY, RabbitMQPublisher
from app.observability.logging import configure_logging, log_event
from app.observability.server import start_internal_metrics_server, stop_internal_metrics_server
from app.outbox.readiness import clear_outbox_relay_ready, mark_outbox_relay_ready
from app.outbox.relay import FencedOutboxRelay
from app.outbox.repository import SqlAlchemyOutboxRepository


async def _heartbeat(event_type: str, owner: str, stopped: asyncio.Event) -> None:
    while not stopped.is_set():
        await mark_outbox_relay_ready(event_type=event_type, owner=owner)
        try:
            await asyncio.wait_for(stopped.wait(), timeout=5.0)
        except TimeoutError:
            continue


async def _run(owner: str, *, event_type: str, watch: bool, poll_interval: float) -> None:
    metrics_server = await start_internal_metrics_server()
    try:
        async with session_factory() as session, RabbitMQPublisher() as publisher:
            relay = FencedOutboxRelay(
                SqlAlchemyOutboxRepository(session),
                publisher,
                owner=owner,
                event_type=event_type,
            )
            stopped = asyncio.Event()
            heartbeat: asyncio.Task[None] | None = None
            try:
                await mark_outbox_relay_ready(event_type=event_type, owner=owner)
                heartbeat = asyncio.create_task(_heartbeat(event_type, owner, stopped))
                while True:
                    result = await relay.run_once()
                    if result.claimed:
                        log_event(
                            "outbox.relay.batch",
                            event_type=event_type,
                            outcome="completed",
                            count=result.claimed,
                        )
                    if not watch:
                        return
                    await asyncio.sleep(poll_interval)
            finally:
                stopped.set()
                if heartbeat is not None:
                    with suppress(Exception):
                        await heartbeat
                with suppress(Exception):
                    await clear_outbox_relay_ready(event_type=event_type, owner=owner)
    finally:
        await stop_internal_metrics_server(metrics_server)


async def _run_and_dispose(
    owner: str,
    *,
    event_type: str,
    watch: bool,
    poll_interval: float,
) -> None:
    try:
        await _run(
            owner,
            event_type=event_type,
            watch=watch,
            poll_interval=poll_interval,
        )
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", default="local-outbox-relay")
    parser.add_argument("--event-type", default=CHAT_ROUTING_KEY)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=0.25)
    args = parser.parse_args(argv)
    configure_logging(service="mosaic-outbox-relay", version=settings.app_version)
    if args.poll_interval <= 0:
        raise ValueError("poll interval must be positive")
    try:
        asyncio.run(
            _run_and_dispose(
                args.owner,
                event_type=args.event_type,
                watch=args.watch,
                poll_interval=args.poll_interval,
            )
        )
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
