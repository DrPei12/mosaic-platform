from __future__ import annotations

from typing import ClassVar, Self
from uuid import uuid4

import pytest

import app.conversations.billing_adapter as billing_module
from app.conversations.billing_adapter import SqlAlchemyChatBillingAdapter


class _Rows:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return self._rows


class _Session:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, *_: object) -> _Rows:
        return _Rows(self.rows)


class _BillingService:
    captures: ClassVar[list[dict[str, object]]] = []
    releases: ClassVar[list[dict[str, object]]] = []

    def __init__(self, _session: _Session) -> None:
        pass

    async def capture(self, **kwargs: object) -> None:
        self.captures.append(kwargs)

    async def release(self, **kwargs: object) -> None:
        self.releases.append(kwargs)


@pytest.mark.asyncio
async def test_succeeded_reservation_is_captured_during_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    reservation_id = uuid4()
    rows = [
        (
            tenant_id,
            reservation_id,
            "succeeded",
            uuid4(),
        )
    ]

    def sessions() -> _Session:
        return _Session(rows)

    _BillingService.captures = []
    _BillingService.releases = []
    monkeypatch.setattr(billing_module, "SqlAlchemyBillingService", _BillingService)

    repaired = await SqlAlchemyChatBillingAdapter(sessions).reconcile_once()

    assert repaired == 1
    assert _BillingService.captures == [
        {"tenant_id": tenant_id, "reservation_id": reservation_id}
    ]
    assert _BillingService.releases == []
