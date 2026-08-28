from datetime import UTC, datetime, timedelta

import pytest

from app.billing.errors import BillingInputError
from app.billing.ports import Money
from app.billing.service import (
    _normalize_source_type,
    _require_future_utc,
    _require_positive_reservation_amount,
)
from app.billing.state import (
    InvalidReservationTransition,
    decide_capture,
    decide_release,
    reservation_is_expired,
)


def test_money_is_integer_minor_units_and_normalizes_currency() -> None:
    assert Money(1250, " cny ") == Money(1250, "CNY")
    assert Money(0, "USD").amount_minor == 0

    with pytest.raises((TypeError, ValueError)):
        Money(-1, "CNY")
    with pytest.raises((TypeError, ValueError)):
        Money(1.5, "CNY")  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        Money(1, "CN")


def test_reserve_input_rejects_zero_amount_and_invalid_expiry() -> None:
    with pytest.raises(BillingInputError):
        # The service performs this check before opening a database transaction.
        _require_positive_reservation_amount(Money(0, "CNY"))

    with pytest.raises(BillingInputError):
        _require_future_utc(datetime.now(UTC) - timedelta(seconds=1))
    assert _normalize_source_type("Inference_Request") == "inference_request"


def test_capture_has_a_hard_cap_and_calculates_release() -> None:
    decision = decide_capture(
        status="pending",
        reserved_minor=100,
        actual_minor=70,
        captured_minor=None,
    )
    assert decision.charged_minor == 70
    assert decision.released_minor == 30
    assert not decision.idempotent

    with pytest.raises(InvalidReservationTransition):
        decide_capture(
            status="pending",
            reserved_minor=100,
            actual_minor=101,
            captured_minor=None,
        )


def test_terminal_capture_is_idempotent_only_for_same_amount() -> None:
    decision = decide_capture(
        status="committed",
        reserved_minor=100,
        actual_minor=70,
        captured_minor=70,
    )
    assert decision.idempotent
    assert decision.released_minor == 30

    with pytest.raises(InvalidReservationTransition):
        decide_capture(
            status="committed",
            reserved_minor=100,
            actual_minor=60,
            captured_minor=70,
        )


def test_release_is_idempotent_and_terminal_capture_cannot_release() -> None:
    first = decide_release(status="pending", reserved_minor=100)
    replay = decide_release(status="released", reserved_minor=100)
    assert first.released_minor == replay.released_minor == 100
    assert replay.idempotent

    with pytest.raises(InvalidReservationTransition):
        decide_release(status="committed", reserved_minor=100)


def test_reservation_expiry_requires_timezone_aware_cutoff() -> None:
    now = datetime.now(UTC)
    assert reservation_is_expired(expires_at=now - timedelta(seconds=1), now=now)
    assert not reservation_is_expired(expires_at=now + timedelta(seconds=1), now=now)

    with pytest.raises(ValueError):
        reservation_is_expired(expires_at=now.replace(tzinfo=None), now=now)
