from unittest.mock import AsyncMock

import pytest

import app.infrastructure.redis as redis_module


@pytest.mark.asyncio
async def test_redis_probe_reports_ping_result(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.ping.return_value = True
    monkeypatch.setattr(redis_module, "redis_client", client)

    assert await redis_module.probe_redis() is True
    client.ping.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_redis_probe_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.ping.side_effect = OSError("redis unavailable")
    monkeypatch.setattr(redis_module, "redis_client", client)

    assert await redis_module.probe_redis() is False


@pytest.mark.asyncio
async def test_redis_disposal_closes_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    monkeypatch.setattr(redis_module, "redis_client", client)

    await redis_module.dispose_redis()

    client.aclose.assert_awaited_once_with()
