from __future__ import annotations

import asyncio

import pytest

from app.generations import readiness
from scripts import generation_consumer


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[object, ...]] = []
        self.eval_calls: list[tuple[object, ...]] = []

    async def set(self, key: object, value: object, **kwargs: object) -> None:
        self.values[str(key)] = str(value)
        self.set_calls.append((key, value, kwargs))

    async def eval(self, *args: object) -> int:
        self.eval_calls.append(args)
        key = str(args[2])
        owner = str(args[3])
        if self.values.get(key) == owner:
            del self.values[key]
            return 1
        return 0

    async def exists(self, key: object) -> int:
        return int(str(key) in self.values)


@pytest.mark.asyncio
async def test_media_and_video_workers_have_independent_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _Redis()
    monkeypatch.setattr(readiness, "redis_client", redis)

    await readiness.mark_generation_media_worker_ready(worker_id="media-a")
    await readiness.mark_generation_video_worker_ready(worker_id="video-a")

    assert redis.set_calls == [
        (
            readiness.GENERATION_MEDIA_WORKER_HEARTBEAT_KEY,
            "media-a",
            {"ex": 15},
        ),
        (
            readiness.GENERATION_VIDEO_WORKER_HEARTBEAT_KEY,
            "video-a",
            {"ex": 15},
        ),
    ]
    assert await readiness.is_generation_media_worker_ready() is True
    assert await readiness.is_generation_video_worker_ready() is True
    assert await readiness.are_generation_workers_ready() is True

    await readiness.clear_generation_media_worker_ready(worker_id="other-worker")
    assert await readiness.is_generation_media_worker_ready() is True
    await readiness.clear_generation_media_worker_ready(worker_id="media-a")

    assert await readiness.is_generation_media_worker_ready() is False
    assert await readiness.is_generation_video_worker_ready() is True
    assert await readiness.are_generation_workers_ready() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_kind", ["media", "video"])
async def test_generation_consumer_heartbeat_uses_queue_specific_worker_kind(
    monkeypatch: pytest.MonkeyPatch,
    worker_kind: str,
) -> None:
    calls: list[tuple[str, str]] = []
    stopped = asyncio.Event()

    async def mark(*, worker_id: str, worker_kind: str) -> None:
        calls.append((worker_id, worker_kind))
        stopped.set()

    monkeypatch.setattr(generation_consumer, "mark_generation_worker_ready", mark)

    await generation_consumer._heartbeat(
        "worker-a",
        stopped,
        worker_kind=worker_kind,  # type: ignore[arg-type]
    )

    assert calls == [("worker-a", worker_kind)]
