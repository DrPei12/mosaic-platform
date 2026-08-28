"""DashScope provider adapters.

Only the official provider contracts are implemented here:

* OpenAI-compatible chat completions for text;
* native multimodal generation for Qwen Image and Qwen TTS;
* native asynchronous video synthesis for Wan.

There are no retries in this adapter.  In particular, a retry of a chargeable
POST can create duplicate paid generations.  Retry/admission policy belongs to
the application job layer, where idempotency and billing reservations exist.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Mapping
from typing import Any, Self, TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.providers.config import (
    ProviderCredential,
    ProviderSettings,
)
from app.providers.errors import ProviderError, ProviderProtocolError
from app.providers.ports import (
    AudioGenerationRequest,
    AudioGenerationResult,
    AudioUsage,
    ChatMessage,
    ImageArtifact,
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageUsage,
    RemoteAsset,
    TextCompletionRequest,
    TextCompletionResult,
    TextStreamChunk,
    Usage,
    VideoGenerationRequest,
    VideoTaskResult,
    VideoTaskStatus,
    VideoUsage,
)

PROVIDER_NAME = "dashscope"
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _WireUsage(_WireModel):
    prompt_tokens: int | None = 0
    completion_tokens: int | None = 0
    total_tokens: int | None = 0


class _TextMessage(_WireModel):
    content: str = ""


class _TextChoice(_WireModel):
    message: _TextMessage
    finish_reason: str | None = None


class _TextResponse(_WireModel):
    id: str
    model: str
    choices: list[_TextChoice]
    usage: _WireUsage | None = None


class _StreamDelta(_WireModel):
    content: str | None = None


class _StreamChoice(_WireModel):
    delta: _StreamDelta
    finish_reason: str | None = None


class _StreamResponse(_WireModel):
    id: str
    model: str = ""
    choices: list[_StreamChoice] = Field(default_factory=list)
    usage: _WireUsage | None = None


class _ImageUsageWire(_WireModel):
    image_count: int | None = None
    output_image_count: int | None = None


class _ImageContent(_WireModel):
    image: str | None = None
    b64_json: str | None = Field(default=None, alias="b64_json")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _ImageMessage(_WireModel):
    content: list[_ImageContent]


class _ImageChoice(_WireModel):
    message: _ImageMessage


class _ImageOutput(_WireModel):
    choices: list[_ImageChoice]
    usage: _ImageUsageWire | None = None


class _ImageResponse(_WireModel):
    output: _ImageOutput
    request_id: str | None = None
    usage: _ImageUsageWire | None = None


class _VideoSubmitOutput(_WireModel):
    task_id: str


class _VideoUsageWire(_WireModel):
    duration: int | float | None = None
    duration_seconds: int | float | None = None
    output_video_duration: int | float | None = None
    video_count: int | None = None
    ratio: str | None = None
    resolution: str | None = None
    sr: int | str | None = Field(default=None, alias="SR")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _VideoSubmitResponse(_WireModel):
    output: _VideoSubmitOutput
    request_id: str | None = None
    usage: _VideoUsageWire | None = None


class _VideoTaskOutput(_WireModel):
    task_status: str
    video_url: str | None = None
    duration: int | float | None = None
    duration_seconds: int | float | None = None
    output_video_duration: int | float | None = None
    video_count: int | None = None
    ratio: str | None = None
    resolution: str | None = None
    sr: int | str | None = Field(default=None, alias="SR")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _VideoTaskResponse(_WireModel):
    output: _VideoTaskOutput
    request_id: str | None = None
    usage: _VideoUsageWire | None = None


class _AudioUsageWire(_WireModel):
    characters: int | None = None


class _AudioPayload(_WireModel):
    url: str


class _AudioOutput(_WireModel):
    audio: _AudioPayload
    usage: _AudioUsageWire | None = None


class _AudioResponse(_WireModel):
    output: _AudioOutput
    request_id: str | None = None
    usage: _AudioUsageWire | None = None


_WireModelT = TypeVar("_WireModelT", bound=BaseModel)


def _endpoint(base_url: str, path: str) -> str:
    """Join a trusted configured URL and a constant provider path."""

    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _validate_trusted_base_url(value: str, *, allow_test_host: bool) -> None:
    parsed = urlsplit(value)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    official_host = hostname == "dashscope.aliyuncs.com" or bool(
        re.fullmatch(r"[a-z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com", hostname)
    )
    if (
        (parsed.scheme != "https" and not allow_test_host)
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (not official_host and not allow_test_host)
    ):
        raise ValueError("provider base URL must use an allowlisted DashScope HTTPS host")


def _request_id(response: httpx.Response, payload_id: str | None = None) -> str | None:
    value = (
        response.headers.get("x-dashscope-requestid")
        or response.headers.get("x-request-id")
        or payload_id
    )
    if value is None or not value.strip() or value.strip().lower() == "unknown":
        return None
    return value.strip()


def _required_request_id(
    response: httpx.Response,
    payload_id: str | None,
    operation: str,
) -> str:
    value = _request_id(response, payload_id)
    if value is None:
        raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation)
    return value


def _to_usage(value: _WireUsage | None) -> Usage | None:
    if value is None:
        return None
    return Usage(
        prompt_tokens=value.prompt_tokens or 0,
        completion_tokens=value.completion_tokens or 0,
        total_tokens=value.total_tokens or 0,
    )


def _to_image_usage(value: _ImageUsageWire | None) -> ImageUsage | None:
    if value is None:
        return None
    image_count = (
        value.output_image_count
        if value.output_image_count is not None
        else value.image_count
    )
    if image_count is None:
        return None
    return ImageUsage(image_count=image_count)


def _to_audio_usage(value: _AudioUsageWire | None) -> AudioUsage | None:
    if value is None or value.characters is None:
        return None
    return AudioUsage(characters=value.characters)


def _resolution_from_sr(value: int | str | None) -> str | None:
    if value is None:
        return None
    text = str(value).upper()
    return text if text.endswith("P") else f"{text}P"


def _to_video_usage(value: _VideoUsageWire | None) -> VideoUsage | None:
    if value is None:
        return None
    duration = next(
        (
            candidate
            for candidate in (
                value.output_video_duration,
                value.duration_seconds,
                value.duration,
            )
            if candidate is not None
        ),
        None,
    )
    resolution = value.resolution or _resolution_from_sr(value.sr)
    if all(item is None for item in (duration, value.video_count, value.ratio, resolution)):
        return None
    return VideoUsage(
        duration_seconds=int(duration) if duration is not None else None,
        video_count=value.video_count,
        ratio=value.ratio,
        resolution=resolution,
    )


def _to_video_output_usage(value: _VideoTaskOutput) -> VideoUsage | None:
    duration = next(
        (
            candidate
            for candidate in (
                value.output_video_duration,
                value.duration_seconds,
                value.duration,
            )
            if candidate is not None
        ),
        None,
    )
    resolution = value.resolution or _resolution_from_sr(value.sr)
    if all(item is None for item in (duration, value.video_count, value.ratio, resolution)):
        return None
    return VideoUsage(
        duration_seconds=int(duration) if duration is not None else None,
        video_count=value.video_count,
        ratio=value.ratio,
        resolution=resolution,
    )


def _messages_payload(messages: tuple[ChatMessage, ...]) -> list[dict[str, str]]:
    if not messages:
        raise ValueError("at least one chat message is required")
    payload: list[dict[str, str]] = []
    for message in messages:
        if not message.content.strip():
            raise ValueError("chat message content must not be blank")
        payload.append({"role": message.role, "content": message.content})
    return payload


def _validate_asset_url(value: str) -> RemoteAsset:
    try:
        return RemoteAsset.from_url(value)
    except ValueError:
        raise ProviderProtocolError(provider=PROVIDER_NAME, operation="asset_response") from None


def _normalise_video_status(value: str) -> VideoTaskStatus:
    normalised = value.strip().upper()
    aliases = {
        "SUCCESS": VideoTaskStatus.SUCCEEDED,
        "SUCCEEDED": VideoTaskStatus.SUCCEEDED,
        "CANCELLED": VideoTaskStatus.CANCELED,
        "CANCELED": VideoTaskStatus.CANCELED,
    }
    try:
        return aliases.get(normalised, VideoTaskStatus(normalised))
    except ValueError:
        raise ProviderProtocolError(provider=PROVIDER_NAME, operation="video_task_response") from None


class DashScopeProvider:
    """Async DashScope implementation of the typed provider ports."""

    def __init__(
        self,
        credential: ProviderCredential,
        *,
        settings: ProviderSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        resolved = settings or ProviderSettings()
        _validate_trusted_base_url(
            resolved.text_base_url,
            allow_test_host=client is not None,
        )
        _validate_trusted_base_url(
            resolved.native_base_url,
            allow_test_host=client is not None,
        )
        self._credential = credential
        self._settings = resolved
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(resolved.dashscope_timeout_seconds),
            headers={
                "Authorization": credential.authorization_header(),
                "Content-Type": "application/json",
            },
        )

    @classmethod
    def from_env(
        cls,
        *,
        settings: ProviderSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> DashScopeProvider:
        resolved = settings or ProviderSettings()
        return cls(ProviderCredential.from_env(resolved), settings=resolved, client=client)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete(self, request: TextCompletionRequest) -> TextCompletionResult:
        operation = "text_complete"
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": _messages_payload(request.messages),
            "stream": False,
            "enable_thinking": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_completion_tokens is not None:
            payload["max_completion_tokens"] = request.max_completion_tokens
        response = await self._post(
            _endpoint(self._settings.text_base_url, "/chat/completions"), payload, operation
        )
        parsed = self._parse(response, _TextResponse, operation)
        if not parsed.choices:
            raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation)
        choice = parsed.choices[0]
        if parsed.model != request.model:
            raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation)
        return TextCompletionResult(
            request_id=_required_request_id(response, None, operation),
            model=parsed.model,
            content=choice.message.content,
            finish_reason=choice.finish_reason,
            usage=_to_usage(parsed.usage),
        )

    async def stream(self, request: TextCompletionRequest) -> AsyncIterator[TextStreamChunk]:
        operation = "text_stream"
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": _messages_payload(request.messages),
            "stream": True,
            "enable_thinking": False,
            "stream_options": {"include_usage": True},
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_completion_tokens is not None:
            payload["max_completion_tokens"] = request.max_completion_tokens

        saw_done = False
        saw_terminal = False
        saw_usage = False
        try:
            async with self._client.stream(
                "POST",
                _endpoint(self._settings.text_base_url, "/chat/completions"),
                json=payload,
                headers=self._request_headers(),
                timeout=self._settings.dashscope_timeout_seconds,
            ) as response:
                self._ensure_success(response, operation, chargeable=True)
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        saw_done = True
                        break
                    try:
                        parsed = _StreamResponse.model_validate(json.loads(data))
                    except (ValueError, ValidationError):
                        raise ProviderProtocolError(
                            provider=PROVIDER_NAME,
                            operation=operation,
                        ) from None
                    if parsed.model and parsed.model != request.model:
                        raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation)
                    if parsed.usage is not None:
                        if saw_usage:
                            raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation)
                        saw_usage = True
                    if not parsed.choices:
                        if parsed.usage is None:
                            raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation)
                        yield TextStreamChunk(
                            request_id=_required_request_id(response, None, operation),
                            model=parsed.model or request.model,
                            delta="",
                            finish_reason=None,
                            usage=_to_usage(parsed.usage),
                        )
                        continue
                    choice = parsed.choices[0]
                    if choice.finish_reason is not None:
                        saw_terminal = True
                    yield TextStreamChunk(
                        request_id=_required_request_id(response, None, operation),
                        model=parsed.model or request.model,
                        delta=choice.delta.content or "",
                        finish_reason=choice.finish_reason,
                        usage=_to_usage(parsed.usage),
                    )
                if not saw_done or not saw_terminal or not saw_usage:
                    raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation)
        except ProviderError:
            raise
        except (httpx.ConnectTimeout, httpx.ConnectError):
            raise ProviderError(
                provider=PROVIDER_NAME,
                operation=operation,
                code="provider_connection_error",
                message="provider connection could not be established",
                retryable=True,
            ) from None
        except httpx.HTTPError:
            raise ProviderError(
                provider=PROVIDER_NAME,
                operation=operation,
                code="provider_submission_unknown",
                message="provider submission outcome is unknown",
                retryable=False,
            ) from None

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        operation = "image_generate"
        if request.count < 1:
            raise ValueError("image count must be positive")
        payload = {
            "model": request.model,
            "input": {
                "messages": [
                    {"role": "user", "content": [{"text": request.prompt}]},
                ]
            },
            "parameters": {
                "size": request.size,
                "n": request.count,
                "prompt_extend": False,
                "enable_thinking": False,
                "watermark": False,
            },
        }
        response = await self._post(
            _endpoint(
                self._settings.native_base_url,
                "/services/aigc/multimodal-generation/generation",
            ),
            payload,
            operation,
        )
        parsed = self._parse(response, _ImageResponse, operation)
        images: list[ImageArtifact] = []
        for choice in parsed.output.choices:
            for content in choice.message.content:
                if content.image:
                    images.append(ImageArtifact(remote=_validate_asset_url(content.image)))
                elif content.b64_json:
                    images.append(ImageArtifact(data_base64=content.b64_json))
        if not images:
            raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation)
        return ImageGenerationResult(
            request_id=_required_request_id(response, parsed.request_id, operation),
            model=request.model,
            images=tuple(images),
            usage=_to_image_usage(parsed.usage or parsed.output.usage),
        )

    async def submit_video(self, request: VideoGenerationRequest) -> str:
        operation = "video_submit"
        payload = {
            "model": request.model,
            "input": {"prompt": request.prompt},
            "parameters": {
                "resolution": request.resolution,
                "ratio": request.ratio,
                "duration": request.duration_seconds,
                "prompt_extend": False,
                "watermark": False,
            },
        }
        response = await self._post(
            _endpoint(self._settings.native_base_url, "/services/aigc/video-generation/video-synthesis"),
            payload,
            operation,
            extra_headers={"X-DashScope-Async": "enable"},
        )
        parsed = self._parse(response, _VideoSubmitResponse, operation)
        task_id = parsed.output.task_id
        if not _TASK_ID_RE.fullmatch(task_id):
            raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation)
        return task_id

    async def get_video_task(self, task_id: str) -> VideoTaskResult:
        operation = "video_task"
        if not _TASK_ID_RE.fullmatch(task_id):
            raise ValueError("invalid video task id")
        response = await self._get(
            _endpoint(self._settings.native_base_url, f"/tasks/{task_id}"), operation
        )
        parsed = self._parse(response, _VideoTaskResponse, operation)
        status = _normalise_video_status(parsed.output.task_status)
        video = (
            _validate_asset_url(parsed.output.video_url)
            if parsed.output.video_url is not None
            else None
        )
        if status is VideoTaskStatus.SUCCEEDED and video is None:
            raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation)
        return VideoTaskResult(
            task_id=task_id,
            status=status,
            video=video,
            request_id=_request_id(response, parsed.request_id),
            usage=_to_video_usage(parsed.usage) or _to_video_output_usage(parsed.output),
        )

    async def wait_for_video(self, task_id: str) -> VideoTaskResult:
        deadline = asyncio.get_running_loop().time() + self._settings.dashscope_video_timeout_seconds
        while True:
            result = await self.get_video_task(task_id)
            if result.status in {
                VideoTaskStatus.SUCCEEDED,
                VideoTaskStatus.FAILED,
                VideoTaskStatus.CANCELED,
                VideoTaskStatus.UNKNOWN,
            }:
                return result
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ProviderError(
                    provider=PROVIDER_NAME,
                    operation="video_task",
                    code="provider_timeout",
                    message="video generation did not finish before the deadline",
                    retryable=True,
                )
            await asyncio.sleep(min(self._settings.dashscope_video_poll_interval_seconds, remaining))

    async def synthesize(self, request: AudioGenerationRequest) -> AudioGenerationResult:
        operation = "audio_synthesize"
        payload = {
            "model": request.model,
            "input": {
                "text": request.text,
                "voice": request.voice,
                "language_type": request.language_type,
            },
        }
        response = await self._post(
            _endpoint(
                self._settings.native_base_url,
                "/services/aigc/multimodal-generation/generation",
            ),
            payload,
            operation,
        )
        parsed = self._parse(response, _AudioResponse, operation)
        return AudioGenerationResult(
            request_id=_required_request_id(response, parsed.request_id, operation),
            model=request.model,
            audio=_validate_asset_url(parsed.output.audio.url),
            usage=_to_audio_usage(parsed.usage or parsed.output.usage),
        )

    def _request_headers(self) -> dict[str, str]:
        return {
            "Authorization": self._credential.authorization_header(),
            "Content-Type": "application/json",
        }

    async def _post(
        self,
        url: str,
        payload: Mapping[str, Any],
        operation: str,
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        headers = self._request_headers()
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = await self._client.post(
                url,
                json=payload,
                headers=headers,
                timeout=self._settings.dashscope_timeout_seconds,
            )
        except (httpx.ConnectTimeout, httpx.ConnectError):
            raise ProviderError(
                provider=PROVIDER_NAME,
                operation=operation,
                code="provider_connection_error",
                message="provider connection could not be established",
                retryable=True,
            ) from None
        except httpx.HTTPError:
            raise ProviderError(
                provider=PROVIDER_NAME,
                operation=operation,
                code="provider_submission_unknown",
                message="provider submission outcome is unknown",
                retryable=False,
            ) from None
        self._ensure_success(response, operation, chargeable=True)
        return response

    async def _get(self, url: str, operation: str) -> httpx.Response:
        try:
            response = await self._client.get(
                url,
                headers=self._request_headers(),
                timeout=self._settings.dashscope_timeout_seconds,
            )
        except httpx.HTTPError:
            raise ProviderError(
                provider=PROVIDER_NAME,
                operation=operation,
                code="provider_poll_transport_error",
                message="provider task status could not be read",
                retryable=True,
            ) from None
        self._ensure_success(response, operation, chargeable=False)
        return response

    def _ensure_success(self, response: httpx.Response, operation: str, *, chargeable: bool) -> None:
        if response.is_success:
            return
        status = response.status_code
        raise ProviderError(
            provider=PROVIDER_NAME,
            operation=operation,
            code="provider_http_error",
            message="provider returned an HTTP error",
            status_code=status,
            retryable=status == 429
            or ((not chargeable) and (status == 408 or status >= 500)),
            request_id=_request_id(response),
        )

    def _parse(
        self, response: httpx.Response, model: type[_WireModelT], operation: str
    ) -> _WireModelT:
        try:
            body = response.json()
            return model.model_validate(body)
        except (ValueError, ValidationError):
            raise ProviderProtocolError(provider=PROVIDER_NAME, operation=operation) from None
