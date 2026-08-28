"""Ephemeral generation-worker heartbeat for admission and readiness."""

from __future__ import annotations

from typing import Literal

from app.infrastructure.redis import redis_client

GenerationWorkerKind = Literal["media", "video"]

GENERATION_MEDIA_WORKER_HEARTBEAT_KEY = "mosaic:worker:generation:media:ready:v1"
GENERATION_VIDEO_WORKER_HEARTBEAT_KEY = "mosaic:worker:generation:video:ready:v1"
# Keep the existing helper and constant usable for the default media worker.
GENERATION_WORKER_HEARTBEAT_KEY = GENERATION_MEDIA_WORKER_HEARTBEAT_KEY

_HEARTBEAT_KEYS: dict[GenerationWorkerKind, str] = {
    "media": GENERATION_MEDIA_WORKER_HEARTBEAT_KEY,
    "video": GENERATION_VIDEO_WORKER_HEARTBEAT_KEY,
}


def _heartbeat_key(worker_kind: GenerationWorkerKind) -> str:
    try:
        return _HEARTBEAT_KEYS[worker_kind]
    except KeyError:
        raise ValueError("unsupported generation worker kind") from None


async def mark_generation_worker_ready(
    *,
    worker_id: str,
    worker_kind: GenerationWorkerKind = "media",
    ttl_seconds: int = 15,
) -> None:
    if not worker_id.strip() or ttl_seconds < 2:
        raise ValueError("invalid generation worker heartbeat")
    await redis_client.set(_heartbeat_key(worker_kind), worker_id, ex=ttl_seconds)


async def clear_generation_worker_ready(
    *,
    worker_id: str,
    worker_kind: GenerationWorkerKind = "media",
) -> None:
    await redis_client.eval(
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end",
        1,
        _heartbeat_key(worker_kind),
        worker_id,
    )


async def is_generation_worker_ready(*, worker_kind: GenerationWorkerKind = "media") -> bool:
    try:
        return bool(await redis_client.exists(_heartbeat_key(worker_kind)))
    except Exception:  # noqa: BLE001 - admission must fail closed
        return False


async def mark_generation_media_worker_ready(*, worker_id: str, ttl_seconds: int = 15) -> None:
    await mark_generation_worker_ready(
        worker_id=worker_id,
        worker_kind="media",
        ttl_seconds=ttl_seconds,
    )


async def mark_generation_video_worker_ready(*, worker_id: str, ttl_seconds: int = 15) -> None:
    await mark_generation_worker_ready(
        worker_id=worker_id,
        worker_kind="video",
        ttl_seconds=ttl_seconds,
    )


async def clear_generation_media_worker_ready(*, worker_id: str) -> None:
    await clear_generation_worker_ready(worker_id=worker_id, worker_kind="media")


async def clear_generation_video_worker_ready(*, worker_id: str) -> None:
    await clear_generation_worker_ready(worker_id=worker_id, worker_kind="video")


async def is_generation_media_worker_ready() -> bool:
    return await is_generation_worker_ready(worker_kind="media")


async def is_generation_video_worker_ready() -> bool:
    return await is_generation_worker_ready(worker_kind="video")


async def are_generation_workers_ready() -> bool:
    media_ready = await is_generation_media_worker_ready()
    video_ready = await is_generation_video_worker_ready()
    return media_ready and video_ready


async def is_generation_worker_ready_for_modality(modality: str) -> bool:
    if modality == "video":
        return await is_generation_video_worker_ready()
    if modality in {"text", "image", "audio"}:
        return await is_generation_media_worker_ready()
    return False


__all__ = [
    "GENERATION_MEDIA_WORKER_HEARTBEAT_KEY",
    "GENERATION_VIDEO_WORKER_HEARTBEAT_KEY",
    "GENERATION_WORKER_HEARTBEAT_KEY",
    "GenerationWorkerKind",
    "are_generation_workers_ready",
    "clear_generation_media_worker_ready",
    "clear_generation_video_worker_ready",
    "clear_generation_worker_ready",
    "is_generation_media_worker_ready",
    "is_generation_video_worker_ready",
    "is_generation_worker_ready",
    "is_generation_worker_ready_for_modality",
    "mark_generation_media_worker_ready",
    "mark_generation_video_worker_ready",
    "mark_generation_worker_ready",
]
