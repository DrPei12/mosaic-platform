"""Declare and close the configured RabbitMQ topology without publishing work."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.messaging.rabbitmq import RabbitMQPublisher


async def _run() -> None:
    async with RabbitMQPublisher():
        pass


def main() -> int:
    asyncio.run(_run())
    print("rabbitmq topology declaration: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
