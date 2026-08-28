import json
from collections.abc import Callable

import httpx
import pytest

from app.providers.config import ProviderCredential, ProviderSettings
from app.providers.dashscope import DashScopeProvider
from app.providers.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderProtocolError,
)
from app.providers.ports import (
    AudioGenerationRequest,
    ChatMessage,
    ImageArtifact,
    ImageGenerationRequest,
    RemoteAsset,
    TextCompletionRequest,
    VideoGenerationRequest,
    VideoTaskStatus,
)


def _settings() -> ProviderSettings:
    return ProviderSettings(
        dashscope_text_base_url="https://text.example/v1",
        dashscope_native_base_url="https://native.example/api/v1",
        dashscope_video_poll_interval_seconds=0.001,
        dashscope_video_timeout_seconds=1.0,
    )


async def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[DashScopeProvider, httpx.AsyncClient]:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DashScopeProvider.from_env(settings=_settings(), client=client)
    return provider, client


@pytest.mark.asyncio
async def test_text_complete_uses_openai_compatible_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://text.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer unit-test-key"
        body = json.loads(request.content)
        assert body == {
            "model": "qwen3.5-plus",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": False,
            "enable_thinking": False,
            "max_completion_tokens": 32,
            "temperature": 0.1,
        }
        return httpx.Response(
            200,
            headers={"x-dashscope-requestid": "request-unit-1"},
            json={
                "id": "chat-unit-1",
                "model": "qwen3.5-plus",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "你好"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
            request=request,
        )

    provider, client = await _provider(handler, monkeypatch)
    try:
        result = await provider.complete(
            TextCompletionRequest(
                model="qwen3.5-plus",
                messages=(ChatMessage(role="user", content="Say hello"),),
                temperature=0.1,
                max_completion_tokens=32,
            )
        )
    finally:
        await provider.aclose()
        await client.aclose()

    assert result.content == "你好"
    assert result.usage is not None
    assert result.usage.total_tokens == 3


@pytest.mark.asyncio
async def test_text_stream_parses_sse_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body_json = json.loads(request.content)
        assert "max_tokens" not in body_json
        assert body_json["enable_thinking"] is False
        assert body_json["stream_options"] == {"include_usage": True}
        body = (
            'data: {"id":"stream-1","model":"qwen3.5-plus","choices":'
            '[{"delta":{"content":"你"},"finish_reason":null}]}\n\n'
            'data: {"id":"stream-1","model":"qwen3.5-plus","choices":'
            '[{"delta":{"content":"好"},"finish_reason":"stop"}]}\n\n'
            'data: {"id":"stream-1","model":"qwen3.5-plus","choices":[],'
            '"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            headers={
                "content-type": "text/event-stream",
                "x-dashscope-requestid": "request-stream-1",
            },
            content=body.encode(),
            request=request,
        )

    provider, client = await _provider(handler, monkeypatch)
    try:
        chunks = [
            chunk
            async for chunk in provider.stream(
                TextCompletionRequest(
                    model="qwen3.5-plus",
                    messages=(ChatMessage(role="user", content="hello"),),
                )
            )
        ]
    finally:
        await provider.aclose()
        await client.aclose()

    assert [chunk.delta for chunk in chunks] == ["你", "好", ""]
    assert chunks[1].finish_reason == "stop"
    assert chunks[-1].usage is not None


@pytest.mark.asyncio
async def test_text_stream_rejects_missing_billable_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "text/event-stream",
                "x-dashscope-requestid": "request-stream-1",
            },
            content=(
                b'data: {"id":"stream-1","model":"qwen3.5-plus","choices":'
                b'[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
            request=request,
        )

    provider, client = await _provider(handler, monkeypatch)
    try:
        with pytest.raises(ProviderProtocolError):
            _ = [
                chunk
                async for chunk in provider.stream(
                    TextCompletionRequest(
                        model="qwen3.5-plus",
                        messages=(ChatMessage(role="user", content="hello"),),
                    )
                )
            ]
    finally:
        await provider.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_image_generation_uses_native_multimodal_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://native.example/api/v1/services/aigc/multimodal-generation/generation"
        body = json.loads(request.content)
        assert body["model"] == "qwen-image-3.0-pro"
        assert body["input"]["messages"][0]["content"] == [{"text": "a red kite"}]
        assert body["parameters"] == {
            "size": "512*512",
            "n": 1,
            "prompt_extend": False,
            "enable_thinking": False,
            "watermark": False,
        }
        return httpx.Response(
            200,
            json={
                "request_id": "image-1",
                "output": {
                    "choices": [{"message": {"content": [{"image": "https://assets.aliyuncs.com/image.png?sig=secret"}]}}]
                },
                "usage": {"output_image_count": 1},
            },
            request=request,
        )

    provider, client = await _provider(handler, monkeypatch)
    try:
        result = await provider.generate(
            ImageGenerationRequest(model="qwen-image-3.0-pro", prompt="a red kite")
        )
    finally:
        await provider.aclose()
        await client.aclose()

    assert result.images[0].remote is not None
    assert result.images[0].remote.url.endswith("?sig=secret")
    assert "sig=secret" not in repr(result.images[0])
    assert result.usage is not None
    assert result.usage.image_count == 1


@pytest.mark.asyncio
async def test_native_success_without_request_id_is_not_live_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"image": "https://assets.aliyuncs.com/image.png"}
                                ]
                            }
                        }
                    ]
                },
                "usage": {"output_image_count": 1},
            },
            request=request,
        )

    provider, client = await _provider(handler, monkeypatch)
    try:
        with pytest.raises(ProviderProtocolError) as error:
            await provider.generate(
                ImageGenerationRequest(model="qwen-image-3.0-pro", prompt="a red kite")
            )
    finally:
        await provider.aclose()
        await client.aclose()

    assert error.value.__cause__ is None


@pytest.mark.asyncio
async def test_video_submit_and_poll_are_separate_native_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method + " " + request.url.path)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["model"] == "wan2.7-t2v"
            assert body["parameters"] == {
                "resolution": "720P",
                "ratio": "16:9",
                "duration": 2,
                "prompt_extend": False,
                "watermark": False,
            }
            return httpx.Response(
                200,
                json={"request_id": "video-submit-1", "output": {"task_id": "task_123"}},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "request_id": "video-task-1",
                "output": {
                    "task_status": "SUCCEEDED",
                    "video_url": "https://assets.aliyuncs.com/video.mp4?sig=secret",
                },
                "usage": {
                    "output_video_duration": 2,
                    "video_count": 1,
                    "ratio": "16:9",
                    "SR": 720,
                },
            },
            request=request,
        )

    provider, client = await _provider(handler, monkeypatch)
    try:
        task_id = await provider.submit_video(
            VideoGenerationRequest(model="wan2.7-t2v", prompt="a kite over a lake")
        )
        result = await provider.get_video_task(task_id)
    finally:
        await provider.aclose()
        await client.aclose()

    assert task_id == "task_123"
    assert result.status is VideoTaskStatus.SUCCEEDED
    assert result.video is not None
    assert result.usage is not None
    assert result.usage.duration_seconds == 2
    assert result.usage.video_count == 1
    assert result.usage.ratio == "16:9"
    assert result.usage.resolution == "720P"
    assert calls == [
        "POST /api/v1/services/aigc/video-generation/video-synthesis",
        "GET /api/v1/tasks/task_123",
    ]


@pytest.mark.asyncio
async def test_expired_provider_video_task_maps_to_unknown_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "request_id": "video-task-expired",
                "output": {"task_status": "UNKNOWN"},
            },
            request=request,
        )

    provider, client = await _provider(handler, monkeypatch)
    try:
        result = await provider.wait_for_video("task_expired")
    finally:
        await provider.aclose()
        await client.aclose()

    assert result.status is VideoTaskStatus.UNKNOWN


@pytest.mark.asyncio
async def test_audio_generation_parses_native_audio_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {
            "model": "qwen3-tts-flash",
            "input": {"text": "你好", "voice": "Cherry", "language_type": "Chinese"},
        }
        return httpx.Response(
            200,
            json={
                "request_id": "audio-1",
                "output": {"audio": {"url": "https://assets.aliyuncs.com/audio.wav?sig=secret"}},
                "usage": {"characters": 2},
            },
            request=request,
        )

    provider, client = await _provider(handler, monkeypatch)
    try:
        result = await provider.synthesize(
            AudioGenerationRequest(model="qwen3-tts-flash", text="你好")
        )
    finally:
        await provider.aclose()
        await client.aclose()

    assert result.audio.url.endswith("?sig=secret")
    assert repr(result.audio) == "RemoteAsset(<redacted-url>)"
    assert result.usage is not None
    assert result.usage.characters == 2


@pytest.mark.asyncio
async def test_chargeable_http_error_does_not_retry_and_is_sanitised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            headers={"X-DashScope-RequestId": "req-1"},
            content=b'{"message":"secret api_key=unit-test-key"}',
            request=request,
        )

    provider, client = await _provider(handler, monkeypatch)
    try:
        with pytest.raises(ProviderError) as error:
            await provider.generate(
                ImageGenerationRequest(model="qwen-image-3.0-pro", prompt="a red kite")
            )
    finally:
        await provider.aclose()
        await client.aclose()

    assert calls == 1
    assert error.value.public_dict() == {
        "code": "provider_http_error",
        "message": "provider returned an HTTP error",
        "status_code": 503,
        "retryable": False,
        "request_id": "req-1",
    }
    assert error.value.diagnostic_dict()["provider"] == "dashscope"
    assert error.value.diagnostic_dict()["operation"] == "image_generate"
    assert "unit-test-key" not in repr(error.value)


def test_missing_process_credential_is_explicit_skip_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(ProviderConfigurationError) as error:
        DashScopeProvider.from_env(settings=_settings())
    assert error.value.code == "provider_not_configured"
    assert error.value.public_dict()["message"] == "provider credentials are not configured"


@pytest.mark.parametrize(
    "value",
    [
        "staging-placeholder",
        "REPLACE_WITH_PROVIDER_KEY_FROM_SECRET_INJECTOR",
        "ci-not-a-provider-key",
        "dummy-provider-credential",
        "fake-provider-credential",
    ],
)
def test_placeholder_provider_credentials_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", value)

    with pytest.raises(ProviderConfigurationError):
        ProviderCredential.from_env()


def test_process_credential_and_settings_repr_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-key")
    settings = _settings()
    credential = ProviderCredential.from_env(settings)

    assert "unit-test-key" not in repr(settings)
    assert "unit-test-key" not in repr(credential)
    assert str(credential) == "<redacted>"


def test_production_provider_rejects_non_dashscope_base_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-key")
    settings = ProviderSettings(
        dashscope_text_base_url="https://credential-thief.example/v1",
        dashscope_native_base_url="https://dashscope.aliyuncs.com/api/v1",
    )
    credential = ProviderCredential.from_env(settings)

    with pytest.raises(ValueError):
        DashScopeProvider(credential, settings=settings)


def test_provider_error_message_redacts_secret_like_values() -> None:
    error = ProviderError(
        provider="dashscope",
        operation="unit",
        code="unit_error",
        message="upstream api_key=unit-test-key was rejected",
    )

    assert "unit-test-key" not in error.message
    assert error.message == "upstream <redacted> was rejected"


def test_provider_error_str_and_direct_key_redaction() -> None:
    error = ProviderError(
        provider="dashscope",
        operation="unit",
        code="unit_error",
        message="upstream rejected sk-redactme1",
    )

    assert str(error) == error.message
    assert "sk-redactme1" not in str(error)


def test_remote_asset_requires_dashscope_host_and_hides_query() -> None:
    asset = RemoteAsset.from_url("https://assets.aliyuncs.com/a.png?signature=secret")
    assert asset.redacted_url == "https://assets.aliyuncs.com/a.png"
    assert "signature=secret" not in repr(asset)
    assert "signature=secret" not in str(asset)
    with pytest.raises(ValueError):
        RemoteAsset.from_url("https://attacker.example/a.png")
    upgraded = RemoteAsset.from_url("http://assets.aliyuncs.com/a.png?signature=secret")
    assert upgraded.url == "https://assets.aliyuncs.com/a.png?signature=secret"
    with pytest.raises(ValueError):
        RemoteAsset.from_url("https://user:password@assets.aliyuncs.com/a.png")


def test_media_inputs_and_image_artifact_invariants() -> None:
    with pytest.raises(ValueError):
        ImageGenerationRequest(model="qwen-image-3.0-pro", prompt=" ")
    with pytest.raises(ValueError):
        ImageGenerationRequest(model="qwen-image-3.0-pro", prompt="x", count=7)
    with pytest.raises(ValueError):
        ImageGenerationRequest(
            model="qwen-image-3.0-pro",
            prompt="x",
            size="4096*4096",
        )
    with pytest.raises(ValueError):
        VideoGenerationRequest(model="wan2.7-t2v", prompt="x", duration_seconds=1)
    with pytest.raises(ValueError):
        VideoGenerationRequest(model="wan2.7-t2v", prompt="x", resolution="480P")
    with pytest.raises(ValueError):
        AudioGenerationRequest(model="qwen3-tts-flash", text=" ")
    with pytest.raises(ValueError):
        ImageArtifact(
            remote=RemoteAsset.from_url("https://assets.aliyuncs.com/a.png"),
            data_base64="aGVsbG8=",
        )


@pytest.mark.asyncio
async def test_chargeable_connect_failure_is_retryable_before_submission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    provider, client = await _provider(handler, monkeypatch)
    try:
        with pytest.raises(ProviderError) as error:
            await provider.generate(
                ImageGenerationRequest(model="qwen-image-3.0-pro", prompt="a red kite")
            )
    finally:
        await provider.aclose()
        await client.aclose()

    assert error.value.code == "provider_connection_error"
    assert error.value.retryable is True


@pytest.mark.asyncio
async def test_chargeable_read_timeout_is_submission_unknown_and_not_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response read timed out", request=request)

    provider, client = await _provider(handler, monkeypatch)
    try:
        with pytest.raises(ProviderError) as error:
            await provider.generate(
                ImageGenerationRequest(model="qwen-image-3.0-pro", prompt="a red kite")
            )
    finally:
        await provider.aclose()
        await client.aclose()

    assert error.value.code == "provider_submission_unknown"
    assert error.value.retryable is False
    assert error.value.__cause__ is None
