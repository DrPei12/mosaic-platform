from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint

from app.infrastructure.models import Base


def test_outbox_model_has_consistent_fenced_lease_columns_and_claim_index() -> None:
    table = Base.metadata.tables["outbox_events"]
    assert {"claim_owner", "lease_token", "lease_expires_at"} <= set(table.c.keys())
    lease_check = next(
        item
        for item in table.constraints
        if isinstance(item, CheckConstraint) and item.name == "ck_outbox_events_lease_consistent"
    )
    assert "lease_token IS NOT NULL" in lease_check.sqltext.text
    claim_index = next(item for item in table.indexes if item.name == "ix_outbox_events_relay_claim")
    assert [column.name for column in claim_index.columns] == [
        "status",
        "event_type",
        "available_at",
        "lease_expires_at",
    ]


def test_fenced_outbox_migration_generates_upgrade_and_downgrade_sql(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))

    command.upgrade(config, "20260824_0005:20260824_0006", sql=True)
    upgrade_sql = capsys.readouterr().out
    assert "ADD COLUMN claim_owner" in upgrade_sql
    assert "CREATE INDEX ix_outbox_events_relay_claim" in upgrade_sql

    command.downgrade(config, "20260824_0006:20260824_0005", sql=True)
    downgrade_sql = capsys.readouterr().out
    assert "DROP COLUMN claim_owner" in downgrade_sql
