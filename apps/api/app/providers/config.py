"""Trusted, process-environment-only provider configuration."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DASHSCOPE_TEXT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_DASHSCOPE_NATIVE_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
_PLACEHOLDER_MARKERS = (
    "replace_with",
    "placeholder",
    "not-a-provider",
    "dummy-provider",
    "fake-provider",
)


class ProviderSettings(BaseSettings):
    """DashScope settings.

    This settings object deliberately disables dotenv loading.  A provider
    credential must come from the process environment or a deployment secret
    injector, never from a checked-in project file.
    """

    dashscope_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="DASHSCOPE_API_KEY",
    )
    # These are deployment-owned settings, not values accepted from an end
    # user request.  URL validation is performed once at provider startup by
    # DashScopeProvider before any model call is made.
    dashscope_text_base_url: str = DEFAULT_DASHSCOPE_TEXT_BASE_URL
    dashscope_native_base_url: str = DEFAULT_DASHSCOPE_NATIVE_BASE_URL
    dashscope_timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)
    dashscope_video_timeout_seconds: float = Field(default=360.0, gt=0.0, le=900.0)
    # DashScope recommends a deliberately slow polling cadence for Wan jobs;
    # the API is asynchronous and polling faster does not speed generation up.
    dashscope_video_poll_interval_seconds: float = Field(default=15.0, gt=0.0, le=60.0)

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=None,
        extra="ignore",
    )

    @property
    def text_base_url(self) -> str:
        return str(self.dashscope_text_base_url).rstrip("/")

    @property
    def native_base_url(self) -> str:
        return str(self.dashscope_native_base_url).rstrip("/")


@dataclass(frozen=True, slots=True)
class ProviderCredential:
    """A redacted credential wrapper.

    The raw value is intentionally private.  Production callers should use
    :meth:`from_env`, which reads only the current process environment.
    """

    _value: SecretStr

    @classmethod
    def from_env(cls, settings: ProviderSettings | None = None) -> ProviderCredential:
        resolved = settings or ProviderSettings()
        secret = resolved.dashscope_api_key
        raw_value = secret.get_secret_value().strip() if secret is not None else ""
        if not raw_value or any(marker in raw_value.casefold() for marker in _PLACEHOLDER_MARKERS):
            from app.providers.errors import ProviderConfigurationError

            raise ProviderConfigurationError(provider="dashscope")
        return cls(SecretStr(raw_value))

    def authorization_header(self) -> str:
        return f"Bearer {self._value.get_secret_value()}"

    def __repr__(self) -> str:
        return "ProviderCredential(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"
