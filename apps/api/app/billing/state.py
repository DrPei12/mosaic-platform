"""Pure reservation state transitions.

The database service persists these decisions inside one transaction.  Keeping
the transition rules pure makes the hard caps and idempotent terminal states
testable without pretending that SQLite is PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ReservationStatus = Literal["pending", "committed", "released", "expired"]


class InvalidReservationTransition(ValueError):
    """The requested transition is not valid for the persisted status."""


@dataclass(frozen=True, slots=True)
class CaptureDecision:
    charged_minor: int
    released_minor: int
    idempotent: bool


@dataclass(frozen=True, slots=True)
class ReleaseDecision:
    released_minor: int
    idempotent: bool


def decide_capture(
    *,
    status: str,
    reserved_minor: int,
    actual_minor: int,
    captured_minor: int | None,
) -> CaptureDecision:
    """Validate a capture and calculate its debit/release split."""

    _require_nonnegative_integer(reserved_minor, "reserved_minor")
    if reserved_minor == 0:
        raise InvalidReservationTransition("reservation amount must be positive")
    _require_nonnegative_integer(actual_minor, "actual_minor")

    if status == "committed":
        if captured_minor is None or actual_minor != captured_minor:
            raise InvalidReservationTransition("committed capture amount differs")
        return CaptureDecision(
            charged_minor=actual_minor,
            released_minor=reserved_minor - actual_minor,
            idempotent=True,
        )
    if status != "pending":
        raise InvalidReservationTransition("reservation is not pending")
    if actual_minor > reserved_minor:
        raise InvalidReservationTransition("actual amount exceeds reservation")
    return CaptureDecision(
        charged_minor=actual_minor,
        released_minor=reserved_minor - actual_minor,
        idempotent=False,
    )


def decide_release(*, status: str, reserved_minor: int) -> ReleaseDecision:
    """Validate a release and return the amount that becomes available."""

    _require_nonnegative_integer(reserved_minor, "reserved_minor")
    if reserved_minor == 0:
        raise InvalidReservationTransition("reservation amount must be positive")
    if status == "released":
        return ReleaseDecision(released_minor=reserved_minor, idempotent=True)
    if status != "pending":
        raise InvalidReservationTransition("reservation is not pending")
    return ReleaseDecision(released_minor=reserved_minor, idempotent=False)


def reservation_is_expired(*, expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("reservation timestamps must be timezone-aware")
    return expires_at <= now


def _require_nonnegative_integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


__all__ = [
    "CaptureDecision",
    "InvalidReservationTransition",
    "ReleaseDecision",
    "ReservationStatus",
    "decide_capture",
    "decide_release",
    "reservation_is_expired",
]
