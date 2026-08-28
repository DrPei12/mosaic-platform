from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Self
from uuid import UUID

import pytest

from app.usage.service import UsageService

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
USER_ID = UUID("00000000-0000-0000-0000-000000000011")


class _Result:
    def __init__(
        self,
        *,
        scalar: object | None = None,
        row: tuple[int, ...] | None = None,
        scalar_rows: tuple[object, ...] = (),
    ) -> None:
        self._scalar = scalar
        self._row = row
        self._scalar_rows = scalar_rows

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def one(self) -> tuple[int, ...]:
        assert self._row is not None
        return self._row

    def scalars(self) -> tuple[object, ...]:
        return self._scalar_rows


class _Transaction:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Session:
    def __init__(self, row_count: int) -> None:
        now = datetime(2026, 8, 26, tzinfo=UTC)
        self._usage_rows = tuple(
            SimpleNamespace(
                id=UUID(int=index + 1),
                actor_user_id=USER_ID,
                inference_request_id=UUID(int=10_000 + index),
                modality="text",
                model_key="qwen-3-5-plus",
                input_tokens=2,
                output_tokens=3,
                billable_units=5,
                charge_amount_minor=7,
                created_at=now,
            )
            for index in range(row_count)
        )
        self._ledger_rows = tuple(
            SimpleNamespace(
                id=UUID(int=20_000 + index),
                reservation_id=UUID(int=30_000 + index),
                entry_type="debit",
                amount_minor=7,
                currency="PTS",
                reference_type="usage",
                created_at=now,
            )
            for index in range(row_count)
        )
        self._row_count = row_count
        self.statements: list[object] = []

    def begin(self) -> _Transaction:
        return _Transaction()

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _Result(
                scalar=SimpleNamespace(
                    currency="PTS",
                    balance_minor=10_000,
                    reserved_minor=100,
                )
            )
        if len(self.statements) == 2:
            return _Result(
                row=(
                    self._row_count,
                    self._row_count * 2,
                    self._row_count * 3,
                    0,
                    0,
                    0,
                    0,
                    self._row_count * 7,
                )
            )
        if len(self.statements) == 3:
            return _Result(scalar_rows=self._usage_rows[:20])
        if len(self.statements) == 4:
            return _Result(scalar_rows=self._ledger_rows[:20])
        raise AssertionError("usage summary issued an unexpected query")


@pytest.mark.asyncio
@pytest.mark.parametrize("usage_count", [1, 1_000])
async def test_usage_summary_keeps_detail_materialization_and_query_count_bounded(
    usage_count: int,
) -> None:
    session = _Session(usage_count)

    response = await UsageService(session).summary(
        tenant_id=TENANT_ID,
        actor_user_id=USER_ID,
        role="owner",
    )

    assert len(session.statements) == 4
    assert response.currency == "PTS"
    assert response.totals.requests == usage_count
    assert len(response.recent_usage) == min(usage_count, 20)
    assert len(response.recent_ledger) == min(usage_count, 20)
    assert "limit" in str(session.statements[2]).lower()
    assert "limit" in str(session.statements[3]).lower()
