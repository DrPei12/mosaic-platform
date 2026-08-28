"""Opt-in real DashScope integration tests.

These tests are intentionally skipped unless both ``RUN_LIVE_PROVIDER_TESTS``
and ``DASHSCOPE_API_KEY`` are present in the process environment.  A skip is
reported as a skip by pytest and is not an acceptance pass; the production
smoke command is the explicit live gate used by local verification.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.providers.config import ProviderSettings
from app.providers.dashscope import DashScopeProvider
from app.providers.ports import (
    AudioGenerationRequest,
    ChatMessage,
    ImageGenerationRequest,
    TextCompletionRequest,
    VideoGenerationRequest,
    VideoTaskStatus,
)


@pytest_asyncio.fixture
async def live_provider() -> AsyncIterator[DashScopeProvider]:
    if os.environ.get("RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("live provider tests require RUN_LIVE_PROVIDER_TESTS=1")
    settings = ProviderSettings()
    if settings.dashscope_api_key is None or not settings.dashscope_api_key.get_secret_value().strip():
        pytest.skip("live provider tests require DASHSCOPE_API_KEY in the process environment")
    async with DashScopeProvider.from_env(settings=settings) as provider:
        yield provider


@pytest.mark.asyncio
async def test_live_text_completion(live_provider: DashScopeProvider) -> None:
    result = await live_provider.complete(
        TextCompletionRequest(
            model="qwen3.5-plus",
            messages=(ChatMessage(role="user", content="请只回答：连通"),),
            max_completion_tokens=16,
        )
    )
    assert result.request_id
    assert result.content


@pytest.mark.asyncio
async def test_live_image_generation(live_provider: DashScopeProvider) -> None:
    result = await live_provider.generate(
        ImageGenerationRequest(
            model="qwen-image-3.0-pro",
            prompt="一朵蓝色的花，白色背景，简洁插画",
            size="512*512",
            count=1,
        )
    )
    assert result.request_id
    assert len(result.images) >= 1


@pytest.mark.asyncio
async def test_live_video_generation(live_provider: DashScopeProvider) -> None:
    task_id = await live_provider.submit_video(
        VideoGenerationRequest(
            model="wan2.7-t2v",
            prompt="一朵蓝色的花在微风中轻轻摇曳",
            resolution="720P",
            ratio="16:9",
            duration_seconds=2,
        )
    )
    result = await live_provider.wait_for_video(task_id)
    assert result.status is VideoTaskStatus.SUCCEEDED
    assert result.video is not None


@pytest.mark.asyncio
async def test_live_audio_generation(live_provider: DashScopeProvider) -> None:
    result = await live_provider.synthesize(
        AudioGenerationRequest(
            model="qwen3-tts-flash",
            text="这是一次语音连通性测试。",
            voice="Cherry",
            language_type="Chinese",
        )
    )
    assert result.request_id
    assert result.audio.url.startswith("https://")
