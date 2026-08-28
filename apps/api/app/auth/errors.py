"""Stable, non-sensitive authentication errors."""

from __future__ import annotations

from typing import Any


class AuthError(RuntimeError):
    """An error safe to map to the public ErrorResponse contract."""

    __slots__ = ("code", "details", "message", "retryable", "status_code")

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details
        super().__init__(message)

    def __repr__(self) -> str:
        return f"AuthError(status_code={self.status_code!r}, code={self.code!r})"
