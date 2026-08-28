"""Small, persistence-agnostic types used by the fenced outbox relay."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")
_ERROR_CODE = re.compile(r"^[A-Z0-9_]{1,120}$")
_ERROR_PHASE = re.compile(r"^[a-z_]{1,64}$")
_MAX_BACKOFF_SECONDS = 86_400.0
# A broker-confirmed message can outlive a failed/late relay mark. The event ID
# and business CAS are authoritative; a message for a known failed row is still
# safe to consume and prevents confirm-before-mark loss.
DELIVERABLE_OUTBOX_STATUSES = frozenset({"pending", "published", "failed"})


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """An outbox row, optionally carrying the lease that claimed it.

    ``payload`` is intentionally retained for the worker/consumer lookup path,
    but the RabbitMQ envelope is built from the metadata fields only.
    """

    event_id: UUID
    tenant_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    aggregate_version: int
    payload: Mapping[str, Any] = field(repr=False)
    attempts: int = 0
    available_at: datetime | None = None
    claim_owner: str | None = None
    lease_token: UUID | None = None
    lease_expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not _EVENT_TYPE.fullmatch(self.aggregate_type):
            raise ValueError("aggregate_type is invalid")
        if not _EVENT_TYPE.fullmatch(self.event_type):
            raise ValueError("event_type is invalid")
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be positive")
        if self.attempts < 0:
            raise ValueError("attempts must be nonnegative")
        if (self.claim_owner is None) != (self.lease_token is None):
            raise ValueError("claim_owner and lease_token must be provided together")
        if self.available_at is not None:
            object.__setattr__(self, "available_at", _as_utc(self.available_at))
        if self.lease_expires_at is not None:
            object.__setattr__(self, "lease_expires_at", _as_utc(self.lease_expires_at))

    @property
    def claimed(self) -> bool:
        return self.claim_owner is not None and self.lease_token is not None

    def require_lease(self) -> tuple[str, UUID]:
        if self.claim_owner is None or self.lease_token is None:
            raise ValueError("outbox event is not claimed")
        return self.claim_owner, self.lease_token


ClaimedOutboxEvent = OutboxEvent
OutboxRecord = OutboxEvent


@dataclass(frozen=True, slots=True)
class OutboxErrorDetails:
    """The only error data allowed to cross into an outbox row."""

    code: str
    phase: str
    retryable: bool

    def __post_init__(self) -> None:
        if not _ERROR_CODE.fullmatch(self.code):
            raise ValueError("error code is invalid")
        if not _ERROR_PHASE.fullmatch(self.phase):
            raise ValueError("error phase is invalid")

    def as_mapping(self) -> dict[str, str | bool]:
        return {
            "code": self.code,
            "phase": self.phase,
            "retryable": self.retryable,
        }


def sanitize_error_details(
    details: Mapping[str, object] | None = None,
    *,
    default_code: str = "OUTBOX_PUBLISH_FAILED",
    default_phase: str = "publish",
    default_retryable: bool = True,
) -> OutboxErrorDetails:
    """Keep only stable, non-sensitive error fields.

    In particular, exception text, provider response bodies, URLs, headers and
    arbitrary mappings are never copied into the persisted details.
    """

    source = details or {}
    if not _ERROR_CODE.fullmatch(default_code):
        default_code = "OUTBOX_PUBLISH_FAILED"
    if not _ERROR_PHASE.fullmatch(default_phase):
        default_phase = "publish"
    raw_code = source.get("code")
    code = raw_code.strip() if isinstance(raw_code, str) else default_code
    if not _ERROR_CODE.fullmatch(code):
        code = default_code

    raw_phase = source.get("phase")
    phase = raw_phase.strip() if isinstance(raw_phase, str) else default_phase
    if not _ERROR_PHASE.fullmatch(phase):
        phase = default_phase

    raw_retryable = source.get("retryable")
    retryable = raw_retryable if isinstance(raw_retryable, bool) else default_retryable
    return OutboxErrorDetails(code=code, phase=phase, retryable=retryable)


def error_details_from_exception(
    error: BaseException,
    *,
    phase: str = "publish",
    default_retryable: bool = True,
) -> OutboxErrorDetails:
    """Extract only an optional stable ``code`` from an exception."""

    raw_code = getattr(error, "code", None)
    raw_retryable = getattr(error, "retryable", default_retryable)
    retryable = raw_retryable if isinstance(raw_retryable, bool) else default_retryable
    return sanitize_error_details(
        {
            "code": raw_code,
            "phase": phase,
            "retryable": retryable,
        }
    )


def exponential_backoff_seconds(
    attempts: int,
    *,
    base_seconds: float = 1.0,
    max_seconds: float = _MAX_BACKOFF_SECONDS,
) -> float:
    """Return a bounded exponential delay for a 1-based attempt count."""

    if attempts < 1:
        raise ValueError("attempts must be positive")
    if base_seconds <= 0:
        raise ValueError("base_seconds must be positive")
    if max_seconds <= 0:
        raise ValueError("max_seconds must be positive")
    delay = base_seconds * float(2 ** (attempts - 1))
    return min(delay, max_seconds)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry policy shared by relay implementations and tests."""

    max_attempts: int = 5
    base_seconds: float = 1.0
    max_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.base_seconds <= 0:
            raise ValueError("base_seconds must be positive")
        if self.max_seconds <= 0:
            raise ValueError("max_seconds must be positive")

    def delay_seconds(self, attempts: int) -> float:
        return exponential_backoff_seconds(
            attempts,
            base_seconds=self.base_seconds,
            max_seconds=self.max_seconds,
        )

    def should_retry(self, *, attempts: int, retryable: bool) -> bool:
        return retryable and attempts < self.max_attempts


__all__ = [
    "DELIVERABLE_OUTBOX_STATUSES",
    "ClaimedOutboxEvent",
    "OutboxErrorDetails",
    "OutboxEvent",
    "OutboxRecord",
    "RetryPolicy",
    "error_details_from_exception",
    "exponential_backoff_seconds",
    "sanitize_error_details",
]
