from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.outbox.types import (
    DELIVERABLE_OUTBOX_STATUSES,
    RetryPolicy,
    error_details_from_exception,
    exponential_backoff_seconds,
    sanitize_error_details,
)


def test_consumer_accepts_the_confirm_before_mark_race_only() -> None:
    assert DELIVERABLE_OUTBOX_STATUSES == {"pending", "published", "failed"}


def test_error_details_keep_only_safe_fields() -> None:
    details = sanitize_error_details(
        {
            "code": "BROKER_TIMEOUT",
            "phase": "publish",
            "retryable": True,
            "prompt": "do not persist me",
            "exception": "secret provider response",
        }
    )

    assert details.as_mapping() == {
        "code": "BROKER_TIMEOUT",
        "phase": "publish",
        "retryable": True,
    }
    assert "prompt" not in details.as_mapping()
    assert "exception" not in details.as_mapping()


def test_invalid_error_values_fall_back_without_copying_exception_text() -> None:
    details = sanitize_error_details(
        {
            "code": "not a safe code",
            "phase": "provider.response.body",
            "retryable": "yes",
        }
    )

    assert details.as_mapping() == {
        "code": "OUTBOX_PUBLISH_FAILED",
        "phase": "publish",
        "retryable": True,
    }


def test_exception_mapping_uses_only_a_stable_code_attribute() -> None:
    class BrokerError(RuntimeError):
        code = "BROKER_UNAVAILABLE"

    error = BrokerError("prompt=should-never-be-persisted")
    details = error_details_from_exception(error)

    assert details.as_mapping() == {
        "code": "BROKER_UNAVAILABLE",
        "phase": "publish",
        "retryable": True,
    }


def test_exception_retryable_attribute_controls_terminal_marking() -> None:
    class PermanentError(RuntimeError):
        code = "INVALID_EVENT"
        retryable = False

    assert error_details_from_exception(PermanentError()).retryable is False


def test_exponential_backoff_is_bounded_and_attempt_based() -> None:
    assert exponential_backoff_seconds(1, base_seconds=2, max_seconds=10) == 2
    assert exponential_backoff_seconds(2, base_seconds=2, max_seconds=10) == 4
    assert exponential_backoff_seconds(4, base_seconds=2, max_seconds=10) == 10

    with pytest.raises(ValueError):
        exponential_backoff_seconds(0)


def test_retry_policy_stops_at_max_attempts() -> None:
    policy = RetryPolicy(max_attempts=3, base_seconds=1, max_seconds=10)

    assert policy.should_retry(attempts=1, retryable=True) is True
    assert policy.should_retry(attempts=3, retryable=True) is False
    assert policy.should_retry(attempts=1, retryable=False) is False


def test_outbox_event_normalizes_lease_timestamps_to_utc() -> None:
    from app.outbox.types import OutboxEvent

    event = OutboxEvent(
        event_id=uuid4(),
        tenant_id=uuid4(),
        aggregate_type="generation_job",
        aggregate_id=uuid4(),
        event_type="generation.accepted",
        aggregate_version=1,
        payload={"prompt": "retained only for DB lookup"},
        claim_owner="relay-a",
        lease_token=uuid4(),
        lease_expires_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert event.lease_expires_at is not None
    assert event.lease_expires_at.tzinfo == UTC
    assert event.claimed is True
