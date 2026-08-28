"""Fenced transactional-outbox relay primitives.

The outbox package deliberately keeps persistence and publishing separate:
claiming and marking are short database transactions, while the actual broker
publish happens in the relay outside those transactions.
"""

from app.outbox.relay import FencedOutboxRelay, OutboxRelay, RelayBatchResult
from app.outbox.repository import (
    OutboxRepository,
    OutboxSchemaError,
    SqlAlchemyOutboxRepository,
)
from app.outbox.types import (
    ClaimedOutboxEvent,
    OutboxErrorDetails,
    OutboxEvent,
    OutboxRecord,
    RetryPolicy,
    exponential_backoff_seconds,
    sanitize_error_details,
)

__all__ = [
    "ClaimedOutboxEvent",
    "FencedOutboxRelay",
    "OutboxErrorDetails",
    "OutboxEvent",
    "OutboxRecord",
    "OutboxRelay",
    "OutboxRepository",
    "OutboxSchemaError",
    "RelayBatchResult",
    "RetryPolicy",
    "SqlAlchemyOutboxRepository",
    "exponential_backoff_seconds",
    "sanitize_error_details",
]
