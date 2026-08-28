from __future__ import annotations

import pytest

from app.infrastructure.models import OutboxEvents
from app.outbox.repository import (
    SqlAlchemyOutboxRepository,
    normalize_event_types,
)


def test_event_type_filter_normalizes_singular_and_plural_forms() -> None:
    assert normalize_event_types("generation.accepted") == ("generation.accepted",)
    assert normalize_event_types(["generation.accepted", "generation.accepted"]) == (
        "generation.accepted",
    )
    assert normalize_event_types(None) is None

    with pytest.raises(ValueError):
        normalize_event_types("bad event type")


def test_sql_repository_requires_model_backed_fencing_columns() -> None:
    required = set(SqlAlchemyOutboxRepository.required_fencing_columns())
    assert required == {
        "claim_owner",
        "lease_token",
        "lease_expires_at",
    }
    assert required <= set(OutboxEvents.__table__.c.keys())
