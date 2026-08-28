"""Typed billing port consumed by conversation and generation workflows."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.billing.state import ReservationStatus

_CURRENCY = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class Money:
    """An integer amount in the smallest currency unit."""

    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise TypeError("amount_minor must be an integer")
        if self.amount_minor < 0:
            raise ValueError("amount_minor must be non-negative")
        if not isinstance(self.currency, str):
            raise TypeError("currency must be a string")
        normalized = self.currency.strip().upper()
        if not _CURRENCY.fullmatch(normalized):
            raise ValueError("currency must be a three-letter uppercase code")
        object.__setattr__(self, "currency", normalized)


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    """Immutable catalog price facts used by one accepted request/job."""

    price_version_id: UUID
    price_key: str
    version: int
    currency: str
    unit: str
    pricing: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.price_version_id, UUID):
            raise TypeError("price_version_id must be a UUID")
        if not isinstance(self.price_key, str) or not self.price_key.strip():
            raise ValueError("price_key must not be blank")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("price version must be a positive integer")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("price unit must not be blank")
        Money(0, self.currency)
        if not isinstance(self.pricing, Mapping):
            raise TypeError("pricing must be a mapping")
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "pricing", dict(self.pricing))


@dataclass(frozen=True, slots=True)
class BillingUsage:
    """Normalized provider measures consumed by the local tariff."""

    input_tokens: int = 0
    output_tokens: int = 0
    image_count: int = 0
    video_seconds: int = 0
    audio_seconds: int = 0
    character_count: int = 0
    audio_duration_ms: int = 0
    video_duration_ms: int = 0
    storage_bytes: int = 0
    billable_units: int = 0

    def __post_init__(self) -> None:
        values = (
            self.input_tokens,
            self.output_tokens,
            self.image_count,
            self.video_seconds,
            self.audio_seconds,
            self.character_count,
            self.audio_duration_ms,
            self.video_duration_ms,
            self.storage_bytes,
            self.billable_units,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("billing usage values must be integers")
        if any(value < 0 for value in values):
            raise ValueError("billing usage values must be non-negative")


@dataclass(frozen=True, slots=True)
class ReservationResult:
    reservation_id: UUID
    tenant_id: UUID
    source_type: str
    source_id: UUID
    amount: Money
    status: ReservationStatus
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CaptureResult:
    reservation: ReservationResult
    charged: Money
    released: Money
    idempotent: bool


@dataclass(frozen=True, slots=True)
class ReleaseResult:
    reservation: ReservationResult
    released: Money
    idempotent: bool


class BillingAcceptancePort(Protocol):
    """Admission hook that joins the caller's already-open transaction."""

    async def reserve_in_transaction(
        self,
        *,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        price: PriceSnapshot,
        expires_at: datetime,
    ) -> ReservationResult: ...


class BillingSettlementPort(Protocol):
    """Worker-side capture/release boundary; it has no reserve operation."""

    async def capture(
        self,
        *,
        tenant_id: UUID,
        reservation_id: UUID,
        usage: BillingUsage | None = None,
    ) -> CaptureResult: ...

    async def release(
        self,
        *,
        tenant_id: UUID,
        reservation_id: UUID,
    ) -> ReleaseResult: ...


class BillingPort(Protocol):
    """Financial boundary for inference and generation services."""

    async def reserve(
        self,
        *,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        amount: Money,
        expires_at: datetime,
    ) -> ReservationResult: ...

    async def capture(
        self,
        *,
        tenant_id: UUID,
        reservation_id: UUID,
        actual: Money | None = None,
        usage: BillingUsage | None = None,
    ) -> CaptureResult: ...

    async def release(
        self,
        *,
        tenant_id: UUID,
        reservation_id: UUID,
    ) -> ReleaseResult: ...


__all__ = [
    "BillingAcceptancePort",
    "BillingPort",
    "BillingSettlementPort",
    "BillingUsage",
    "CaptureResult",
    "Money",
    "PriceSnapshot",
    "ReleaseResult",
    "ReservationResult",
]
