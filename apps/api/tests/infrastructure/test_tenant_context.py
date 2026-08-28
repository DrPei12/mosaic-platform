from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.infrastructure.tenant_context import (
    _set_transaction_tenant,
    bind_active_transaction_tenant,
    bind_session_tenant,
)


class _Connection:
    def __init__(self) -> None:
        self.parameters: dict[str, str] | None = None

    def execute(self, _statement: object, parameters: dict[str, str]) -> None:
        self.parameters = parameters


class _AsyncSession:
    def __init__(self, *, active: bool) -> None:
        self.info: dict[str, object] = {}
        self.active = active
        self.parameters: dict[str, str] | None = None

    def in_transaction(self) -> bool:
        return self.active

    async def execute(self, _statement: object, parameters: dict[str, str]) -> None:
        self.parameters = parameters


def test_bound_tenant_is_applied_at_each_transaction_begin() -> None:
    tenant_id = uuid4()
    session = SimpleNamespace(info={})
    bind_session_tenant(session, tenant_id)  # type: ignore[arg-type]
    connection = _Connection()

    _set_transaction_tenant(session, object(), connection)  # type: ignore[arg-type]

    assert connection.parameters == {"tenant_id": str(tenant_id)}


def test_database_session_tenant_cannot_change() -> None:
    session = SimpleNamespace(info={})
    bind_session_tenant(session, uuid4())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="cannot change"):
        bind_session_tenant(session, uuid4())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_active_transaction_receives_tenant_immediately() -> None:
    tenant_id = uuid4()
    session = _AsyncSession(active=True)

    await bind_active_transaction_tenant(session, tenant_id)  # type: ignore[arg-type]

    assert session.info["mosaic_tenant_id"] == tenant_id
    assert session.parameters == {"tenant_id": str(tenant_id)}


@pytest.mark.asyncio
async def test_inactive_transaction_defers_tenant_to_begin_hook() -> None:
    tenant_id = uuid4()
    session = _AsyncSession(active=False)

    await bind_active_transaction_tenant(session, tenant_id)  # type: ignore[arg-type]

    assert session.info["mosaic_tenant_id"] == tenant_id
    assert session.parameters is None
