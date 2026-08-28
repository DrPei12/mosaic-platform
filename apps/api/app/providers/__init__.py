"""Provider ports and production integrations.

The provider package deliberately has no demo fallback.  Callers choose a
provider implementation explicitly and provider failures are surfaced as
typed, sanitised exceptions.
"""

from app.providers.config import (
    DEFAULT_DASHSCOPE_NATIVE_BASE_URL,
    DEFAULT_DASHSCOPE_TEXT_BASE_URL,
    ProviderCredential,
    ProviderSettings,
)
from app.providers.dashscope import DashScopeProvider
from app.providers.errors import ProviderConfigurationError, ProviderError
from app.providers.ports import (
    AudioGenerationPort,
    AudioGenerationRequest,
    AudioGenerationResult,
    AudioUsage,
    ChatMessage,
    ImageArtifact,
    ImageGenerationPort,
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageUsage,
    RemoteAsset,
    TextCompletionRequest,
    TextCompletionResult,
    TextGenerationPort,
    TextStreamChunk,
    Usage,
    VideoGenerationPort,
    VideoGenerationRequest,
    VideoTaskResult,
    VideoTaskStatus,
    VideoUsage,
)

__all__ = [
    "DEFAULT_DASHSCOPE_NATIVE_BASE_URL",
    "DEFAULT_DASHSCOPE_TEXT_BASE_URL",
    "AudioGenerationPort",
    "AudioGenerationRequest",
    "AudioGenerationResult",
    "AudioUsage",
    "ChatMessage",
    "DashScopeProvider",
    "ImageArtifact",
    "ImageGenerationPort",
    "ImageGenerationRequest",
    "ImageGenerationResult",
    "ImageUsage",
    "ProviderConfigurationError",
    "ProviderCredential",
    "ProviderError",
    "ProviderSettings",
    "RemoteAsset",
    "TextCompletionRequest",
    "TextCompletionResult",
    "TextGenerationPort",
    "TextStreamChunk",
    "Usage",
    "VideoGenerationPort",
    "VideoGenerationRequest",
    "VideoTaskResult",
    "VideoTaskStatus",
    "VideoUsage",
]
