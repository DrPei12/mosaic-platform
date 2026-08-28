"""Bind authenticated tenant identity to every subsequent SQL transaction."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_SESSION_TENANT_KEY = "mosaic_tenant_id"
_SET_TENANT_SQL = text("SELECT set_config('mosaic.tenant_id', :tenant_id, true)")


def bind_session_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    existing = session.info.get(_SESSION_TENANT_KEY)
    if existing is not None and existing != tenant_id:
        raise RuntimeError("database session tenant cannot change")
    session.info[_SESSION_TENANT_KEY] = tenant_id


async def bind_active_transaction_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Bind a tenant even when SQL has already opened the current transaction.

    Public authentication must first resolve a tenant from global identity
    tables.  By then SQLAlchemy has begun a transaction, so the ``after_begin``
    hook has already run.  Apply the transaction-local PostgreSQL setting
    explicitly in that case while retaining the session guard for every later
    transaction.
    """

    bind_session_tenant(session, tenant_id)
    if session.in_transaction():
        await session.execute(_SET_TENANT_SQL, {"tenant_id": str(tenant_id)})


@event.listens_for(Session, "after_begin")
def _set_transaction_tenant(
    session: Session,
    _transaction: object,
    connection: Connection,
) -> None:
    tenant_id = session.info.get(_SESSION_TENANT_KEY)
    if tenant_id is None:
        return
    connection.execute(_SET_TENANT_SQL, {"tenant_id": str(tenant_id)})


__all__ = ["bind_active_transaction_tenant", "bind_session_tenant"]
