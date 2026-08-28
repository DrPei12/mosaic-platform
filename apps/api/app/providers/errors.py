"""Errors raised by external model providers.

Provider responses are intentionally not included in exception messages.  A
provider can return request metadata, signed URLs, or an echoed credential;
none of those belong in application logs or API responses.
"""

from __future__ import annotations

import re
from typing import Any

_REQUEST_ID_RE = re.compile(r"[^A-Za-z0-9._:-]")
_SECRET_RE = re.compile(
    r"(?i)(?:\b(?:bearer|authorization|api[-_ ]?key|token|secret)\b\s*[:=]?\s*[^\s,;]+|\bsk-[A-Za-z0-9_-]{8,}\b)"
)


def _safe_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _REQUEST_ID_RE.sub("", value)[:128]
    return cleaned or None


def _safe_message(value: str) -> str:
    """Bound and redact a message before it can cross an error boundary."""

    normalised = " ".join(value.split())
    return _SECRET_RE.sub("<redacted>", normalised)[:256]


class ProviderError(RuntimeError):
    """A safe, structured provider failure.

    ``message`` is a stable, non-sensitive application message.  The raw
    provider body is never stored on this object.
    """

    provider: str
    operation: str
    code: str
    message: str
    status_code: int | None
    retryable: bool
    request_id: str | None

    def __init__(
        self,
        *,
        provider: str,
        operation: str,
        code: str,
        message: str,
        status_code: int | None = None,
        retryable: bool = False,
        request_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.operation = operation
        self.code = code
        self.message = _safe_message(message)
        self.status_code = status_code
        self.retryable = retryable
        self.request_id = _safe_request_id(request_id)
        super().__init__(self.message)

    def public_dict(self) -> dict[str, Any]:
        """Return fields safe to expose to an external API client."""

        return {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "request_id": self.request_id,
        }

    def diagnostic_dict(self) -> dict[str, Any]:
        """Return server-side diagnostics; never serialize this to clients."""

        return {
            "provider": self.provider,
            "operation": self.operation,
            **self.public_dict(),
        }

    def __repr__(self) -> str:
        return (
            "ProviderError("
            f"provider={self.provider!r}, operation={self.operation!r}, "
            f"code={self.code!r}, status_code={self.status_code!r}, "
            f"retryable={self.retryable!r}, request_id={self.request_id!r})"
        )


class ProviderConfigurationError(ProviderError):
    """Provider cannot be used because trusted server configuration is absent."""

    def __init__(self, *, provider: str, message: str = "provider credentials are not configured") -> None:
        super().__init__(
            provider=provider,
            operation="configuration",
            code="provider_not_configured",
            message=message,
        )


class ProviderProtocolError(ProviderError):
    """Provider returned a response that does not match the expected contract."""

    def __init__(self, *, provider: str, operation: str) -> None:
        super().__init__(
            provider=provider,
            operation=operation,
            code="invalid_provider_response",
            message="provider returned an invalid response",
        )
