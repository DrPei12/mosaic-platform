from __future__ import annotations

import pytest

from app.messaging.rabbitmq import CHAT_ROUTING_KEY
from app.outbox import readiness


class _Redis:
    def __init__(self) -> None:
        self.set_calls: list[tuple[object, ...]] = []
        self.eval_calls: list[tuple[object, ...]] = []
        self.exists_value = 1

    async def set(self, *args: object, **kwargs: object) -> None:
        self.set_calls.append((args, kwargs))

    async def eval(self, *args: object) -> int:
        self.eval_calls.append(args)
        return 1

    async def exists(self, *_: object) -> int:
        return self.exists_value


@pytest.mark.asyncio
async def test_relay_heartbeat_uses_owner_and_compare_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _Redis()
    monkeypatch.setattr(readiness, "redis_client", redis)

    await readiness.mark_outbox_relay_ready(
        event_type=CHAT_ROUTING_KEY,
        owner="relay-a",
        ttl_seconds=15,
    )
    await readiness.clear_outbox_relay_ready(event_type=CHAT_ROUTING_KEY, owner="relay-a")

    assert redis.set_calls == [(("mosaic:relay:chat:ready:v1", "relay-a"), {"ex": 15})]
    assert len(redis.eval_calls) == 1
    script, keys, key, owner = redis.eval_calls[0]
    assert "redis.call('get', KEYS[1]) == ARGV[1]" in script
    assert keys == 1
    assert key == "mosaic:relay:chat:ready:v1"
    assert owner == "relay-a"


@pytest.mark.asyncio
async def test_relay_readiness_fails_closed_for_unknown_type_or_redis_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError):
        await readiness.mark_outbox_relay_ready(event_type="unknown", owner="relay-a")

    class BrokenRedis:
        async def exists(self, *_: object) -> int:
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(readiness, "redis_client", BrokenRedis())
    assert await readiness.is_outbox_relay_ready(event_type=CHAT_ROUTING_KEY) is False
