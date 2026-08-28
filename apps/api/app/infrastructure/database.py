from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import settings
from app.infrastructure import tenant_context as _tenant_context  # noqa: F401
from app.observability.metrics import REGISTRY, record_db_pool_timeout

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout_seconds,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped session; transactions stay inside services."""

    try:
        async with session_factory() as session:
            yield session
    except SQLAlchemyTimeoutError:
        record_db_pool_timeout()
        raise


async def dispose_engine() -> None:
    await engine.dispose()


async def probe_database() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            if settings.app_environment in {"staging", "production"}:
                safe_role = (
                    await connection.execute(
                        text(
                            "SELECT NOT roles.rolsuper "
                            "AND NOT roles.rolbypassrls "
                            "AND classes.relowner <> roles.oid "
                            "FROM pg_roles AS roles "
                            "JOIN pg_class AS classes ON classes.relname = 'wallet_accounts' "
                            "WHERE roles.rolname = current_user"
                        )
                    )
                ).scalar_one_or_none()
                if safe_role is not True:
                    return False
        return True
    except Exception:  # noqa: BLE001 - readiness must fail closed for any probe failure
        return False


def update_db_pool_metrics() -> None:
    """Refresh pool gauges without issuing a database query."""

    pool = engine.pool
    values: dict[str, int] = {}
    for name in ("size", "checkedout", "checkedin", "overflow"):
        value = getattr(pool, name, None)
        if callable(value):
            value = value()
        if isinstance(value, int) and not isinstance(value, bool):
            values[name] = value
    if "size" in values:
        REGISTRY.set("mosaic_db_pool_size", values["size"])
    if "checkedout" in values:
        REGISTRY.set("mosaic_db_pool_checked_out", values["checkedout"])
    if "checkedin" in values:
        REGISTRY.set("mosaic_db_pool_checked_in", values["checkedin"])
    if "overflow" in values:
        REGISTRY.set("mosaic_db_pool_overflow", values["overflow"])


__all__ = [
    "dispose_engine",
    "engine",
    "get_db_session",
    "probe_database",
    "session_factory",
    "update_db_pool_metrics",
]
