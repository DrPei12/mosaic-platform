"""Typed provider ports shared by API handlers and provider adapters."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol
from urllib.parse import urlsplit

ChatRole = Literal["system", "user", "assistant", "tool"]
_MODEL_MAX_LENGTH = 160
_PROMPT_MAX_LENGTH = 16_000
_TEXT_MAX_LENGTH = 8_000
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_SIZE_RE = re.compile(r"^(?P<width>[0-9]{3,4})\*(?P<height>[0-9]{3,4})$")


def _require_text(value: str, *, name: str, max_length: int) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be blank")
    if len(value) > max_length:
        raise ValueError(f"{name} exceeds the maximum length")


def _require_model(value: str) -> None:
    _require_text(value, name="model", max_length=_MODEL_MAX_LENGTH)


def _require_size(value: str) -> None:
    match = _SIZE_RE.fullmatch(value)
    if match is None:
        raise ValueError("image size must use WIDTH*HEIGHT notation")
    width = int(match.group("width"))
    height = int(match.group("height"))
    if width < 512 or height < 512 or width > 2048 or height > 2048:
        raise ValueError("image dimensions must each be between 512 and 2048 pixels")


def _require_task_id(value: str) -> None:
    if _TASK_ID_RE.fullmatch(value) is None:
        raise ValueError("invalid provider task id")


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: ChatRole
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("unsupported chat message role")
        _require_text(self.content, name="chat message content", max_length=_TEXT_MAX_LENGTH)


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if min(self.prompt_tokens, self.completion_tokens, self.total_tokens) < 0:
            raise ValueError("token usage cannot be negative")


@dataclass(frozen=True, slots=True)
class TextCompletionRequest:
    model: str
    messages: tuple[ChatMessage, ...]
    temperature: float | None = None
    max_completion_tokens: int | None = None

    def __post_init__(self) -> None:
        _require_model(self.model)
        if not self.messages:
            raise ValueError("at least one chat message is required")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_completion_tokens is not None and self.max_completion_tokens < 1:
            raise ValueError("max_completion_tokens must be positive")


@dataclass(frozen=True, slots=True)
class TextCompletionResult:
    request_id: str
    model: str
    content: str
    finish_reason: str | None
    usage: Usage | None


@dataclass(frozen=True, slots=True)
class TextStreamChunk:
    request_id: str
    model: str
    delta: str
    finish_reason: str | None
    usage: Usage | None


@dataclass(frozen=True, slots=True)
class ImageGenerationRequest:
    model: str
    prompt: str
    size: str = "512*512"
    count: int = 1

    def __post_init__(self) -> None:
        _require_model(self.model)
        _require_text(self.prompt, name="image prompt", max_length=_PROMPT_MAX_LENGTH)
        _require_size(self.size)
        if not 1 <= self.count <= 6:
            raise ValueError("image count must be between 1 and 6")


@dataclass(frozen=True, slots=True)
class RemoteAsset:
    """A provider-returned URL whose value is hidden from normal repr/logging."""

    _url: str = field(repr=False)

    @classmethod
    def from_url(cls, value: str) -> RemoteAsset:
        parsed = urlsplit(value)
        hostname = parsed.hostname.lower() if parsed.hostname else ""
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or not (hostname == "aliyuncs.com" or hostname.endswith(".aliyuncs.com"))
        ):
            raise ValueError("provider asset URL is not an allowed DashScope asset URL")
        # Some official Qwen3-TTS examples return an http:// result URL. Never
        # download it in cleartext: upgrade only the already allowlisted
        # Alibaba result host while preserving path and signature query.
        if parsed.scheme == "http":
            parsed = parsed._replace(scheme="https")
        return cls(parsed.geturl())

    @property
    def url(self) -> str:
        return self._url

    @property
    def redacted_url(self) -> str:
        parsed = urlsplit(self._url)
        return parsed._replace(query="", fragment="").geturl()

    def __repr__(self) -> str:
        return "RemoteAsset(<redacted-url>)"

    def __str__(self) -> str:
        return "<redacted-url>"


@dataclass(frozen=True, slots=True)
class ImageArtifact:
    remote: RemoteAsset | None = None
    data_base64: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        has_remote = self.remote is not None
        has_base64 = bool(self.data_base64 and self.data_base64.strip())
        if has_remote == has_base64:
            raise ValueError("image artifact must contain exactly one URL or base64 data")

    def __repr__(self) -> str:
        return (
            "ImageArtifact("
            f"has_remote={self.remote is not None}, "
            f"base64_length={len(self.data_base64) if self.data_base64 else 0})"
        )


@dataclass(frozen=True, slots=True)
class ImageGenerationResult:
    request_id: str
    model: str
    images: tuple[ImageArtifact, ...]
    usage: ImageUsage | None = None


@dataclass(frozen=True, slots=True)
class ImageUsage:
    image_count: int = 0

    def __post_init__(self) -> None:
        if self.image_count < 0:
            raise ValueError("image usage cannot be negative")


@dataclass(frozen=True, slots=True)
class VideoGenerationRequest:
    model: str
    prompt: str
    resolution: str = "720P"
    ratio: str = "16:9"
    duration_seconds: int = 2

    def __post_init__(self) -> None:
        _require_model(self.model)
        _require_text(self.prompt, name="video prompt", max_length=_PROMPT_MAX_LENGTH)
        if self.resolution not in {"720P", "1080P"}:
            raise ValueError("Wan 2.7 video resolution must be 720P or 1080P")
        if self.ratio not in {"1:1", "16:9", "9:16", "4:3", "3:4"}:
            raise ValueError("unsupported video ratio")
        if not 2 <= self.duration_seconds <= 15:
            raise ValueError("video duration must be between 2 and 15 seconds")


class VideoTaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VideoTaskResult:
    task_id: str
    status: VideoTaskStatus
    video: RemoteAsset | None = None
    request_id: str | None = None
    usage: VideoUsage | None = None


@dataclass(frozen=True, slots=True)
class VideoUsage:
    duration_seconds: int | None = None
    video_count: int | None = None
    ratio: str | None = None
    resolution: str | None = None

    def __post_init__(self) -> None:
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("video duration usage cannot be negative")
        if self.video_count is not None and self.video_count < 0:
            raise ValueError("video count usage cannot be negative")


@dataclass(frozen=True, slots=True)
class AudioGenerationRequest:
    model: str
    text: str
    voice: str = "Cherry"
    language_type: str = "Chinese"

    def __post_init__(self) -> None:
        _require_model(self.model)
        _require_text(self.text, name="audio text", max_length=_TEXT_MAX_LENGTH)
        _require_text(self.voice, name="audio voice", max_length=160)
        _require_text(self.language_type, name="audio language", max_length=64)


@dataclass(frozen=True, slots=True)
class AudioUsage:
    characters: int = 0

    def __post_init__(self) -> None:
        if self.characters < 0:
            raise ValueError("audio character usage cannot be negative")


@dataclass(frozen=True, slots=True)
class AudioGenerationResult:
    request_id: str
    model: str
    audio: RemoteAsset
    usage: AudioUsage | None = None


class TextGenerationPort(Protocol):
    async def complete(self, request: TextCompletionRequest) -> TextCompletionResult: ...

    def stream(self, request: TextCompletionRequest) -> AsyncIterator[TextStreamChunk]: ...


class ImageGenerationPort(Protocol):
    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult: ...


class VideoGenerationPort(Protocol):
    async def submit_video(self, request: VideoGenerationRequest) -> str: ...

    async def get_video_task(self, task_id: str) -> VideoTaskResult: ...

    async def wait_for_video(self, task_id: str) -> VideoTaskResult: ...


class AudioGenerationPort(Protocol):
    async def synthesize(self, request: AudioGenerationRequest) -> AudioGenerationResult: ...
