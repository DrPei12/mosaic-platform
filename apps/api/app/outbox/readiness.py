"""Ephemeral readiness heartbeats for event-type-specific outbox relays."""

from __future__ import annotations

from app.infrastructure.redis import redis_client
from app.messaging.rabbitmq import CHAT_ROUTING_KEY, GENERATION_ROUTING_KEY

_HEARTBEAT_KEYS = {
    CHAT_ROUTING_KEY: "mosaic:relay:chat:ready:v1",
    GENERATION_ROUTING_KEY: "mosaic:relay:generation:ready:v1",
}


def _heartbeat_key(event_type: str) -> str:
    try:
        return _HEARTBEAT_KEYS[event_type]
    except KeyError:
        raise ValueError("unsupported outbox relay event type") from None


def _validate_owner(owner: str) -> str:
    normalized = owner.strip()
    if not normalized or len(normalized) > 200:
        raise ValueError("outbox relay owner must be 1 to 200 characters")
    return normalized


async def mark_outbox_relay_ready(
    *,
    event_type: str,
    owner: str,
    ttl_seconds: int = 15,
) -> None:
    if ttl_seconds < 2:
        raise ValueError("outbox relay heartbeat ttl must be at least 2 seconds")
    await redis_client.set(
        _heartbeat_key(event_type),
        _validate_owner(owner),
        ex=ttl_seconds,
    )


async def clear_outbox_relay_ready(*, event_type: str, owner: str) -> None:
    await redis_client.eval(
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end",
        1,
        _heartbeat_key(event_type),
        _validate_owner(owner),
    )


async def is_outbox_relay_ready(*, event_type: str) -> bool:
    try:
        return bool(await redis_client.exists(_heartbeat_key(event_type)))
    except Exception:  # noqa: BLE001 - readiness fails closed
        return False


__all__ = [
    "clear_outbox_relay_ready",
    "is_outbox_relay_ready",
    "mark_outbox_relay_ready",
]
