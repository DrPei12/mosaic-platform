"""Ephemeral worker heartbeat used by the chat submission hard gate."""

from __future__ import annotations

from app.infrastructure.redis import redis_client

CHAT_WORKER_HEARTBEAT_KEY = "mosaic:worker:chat:ready:v1"


async def mark_chat_worker_ready(*, worker_id: str, ttl_seconds: int = 15) -> None:
    if not worker_id.strip() or ttl_seconds < 2:
        raise ValueError("invalid chat worker heartbeat")
    await redis_client.set(CHAT_WORKER_HEARTBEAT_KEY, worker_id, ex=ttl_seconds)


async def clear_chat_worker_ready(*, worker_id: str) -> None:
    await redis_client.eval(
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end",
        1,
        CHAT_WORKER_HEARTBEAT_KEY,
        worker_id,
    )


async def is_chat_worker_ready() -> bool:
    try:
        return bool(await redis_client.exists(CHAT_WORKER_HEARTBEAT_KEY))
    except Exception:  # noqa: BLE001 - admission must fail closed
        return False


__all__ = [
    "CHAT_WORKER_HEARTBEAT_KEY",
    "clear_chat_worker_ready",
    "is_chat_worker_ready",
    "mark_chat_worker_ready",
]
