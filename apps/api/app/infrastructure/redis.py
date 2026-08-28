from __future__ import annotations

import json
from contextlib import suppress
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis

from app.conversations.ports import ChatStreamNotifier, ChatStreamSubscription
from app.core.settings import settings
from app.observability.metrics import record_redis_notification_loss

redis_client: Redis = Redis.from_url(
    settings.redis_url,
    decode_responses=False,
    protocol=3,
    socket_connect_timeout=3.0,
    socket_timeout=5.0,
    health_check_interval=30,
)


async def probe_redis() -> bool:
    try:
        return bool(await redis_client.ping())
    except Exception:  # noqa: BLE001 - readiness must fail closed for any probe failure
        return False


async def dispose_redis() -> None:
    await redis_client.aclose()


def chat_stream_channel(*, environment: str, tenant_id: UUID, request_id: UUID) -> str:
    """Return a tenant/request-scoped wake-up channel with no user content."""

    if not environment.strip():
        raise ValueError("environment must not be blank")
    return f"mosaic:{environment}:chat-stream:{tenant_id}:{request_id}"


class RedisChatStreamSubscription(ChatStreamSubscription):
    """One Redis Pub/Sub subscription used only to wake a DB replay loop."""

    def __init__(self, client: Redis, *, channel: str) -> None:
        self._client = client
        self._channel = channel
        self._pubsub: Any | None = None

    async def open(self) -> None:
        if self._pubsub is not None:
            raise RuntimeError("chat stream subscription is already open")
        pubsub = self._client.pubsub()
        self._pubsub = pubsub
        try:
            await pubsub.subscribe(self._channel)
        except Exception:
            await self.close()
            raise

    async def wait(self, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        pubsub = self._pubsub
        if pubsub is None:
            raise RuntimeError("chat stream subscription is not open")
        message = await pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=timeout_seconds,
        )
        return isinstance(message, dict) and message.get("type") == "message"

    async def close(self) -> None:
        pubsub = self._pubsub
        self._pubsub = None
        if pubsub is None:
            return
        with suppress(Exception):
            await pubsub.unsubscribe(self._channel)
        close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                with suppress(Exception):
                    await cast(Any, result)


class RedisChatStreamNotifier(ChatStreamNotifier):
    """Best-effort Redis fan-out; notification loss is repaired by DB replay."""

    def __init__(self, client: Redis, *, environment: str) -> None:
        if not environment.strip():
            raise ValueError("environment must not be blank")
        self._client = client
        self._environment = environment

    def subscribe(
        self,
        *,
        tenant_id: UUID,
        request_id: UUID,
    ) -> RedisChatStreamSubscription:
        return RedisChatStreamSubscription(
            self._client,
            channel=chat_stream_channel(
                environment=self._environment,
                tenant_id=tenant_id,
                request_id=request_id,
            ),
        )

    async def publish(
        self,
        *,
        tenant_id: UUID,
        request_id: UUID,
        sequence: int,
    ) -> None:
        if sequence < 0:
            raise ValueError("sequence must be non-negative")
        # This payload intentionally contains no event type, delta, content or
        # error details. It is only a hint that causes the consumer to replay
        # committed rows from PostgreSQL.
        payload = json.dumps(
            {"request_id": str(request_id), "sequence": sequence},
            separators=(",", ":"),
        )
        try:
            await self._client.publish(
                chat_stream_channel(
                    environment=self._environment,
                    tenant_id=tenant_id,
                    request_id=request_id,
                ),
                payload,
            )
        except Exception:  # noqa: BLE001 - DB commit must not be retried for wake-up loss
            record_redis_notification_loss()
            return


__all__ = [
    "RedisChatStreamNotifier",
    "RedisChatStreamSubscription",
    "chat_stream_channel",
    "dispose_redis",
    "probe_redis",
    "redis_client",
]
