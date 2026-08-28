"""Exercise a real PostgreSQL row lock without touching application tables.

The gate creates one uniquely named, short-lived table in the configured
database, holds a row lock in one transaction, and proves that a second
transaction waits before it can update the same row. It is intentionally not
a replacement for billing-domain acceptance tests; it only proves that the
CI/database path is using PostgreSQL rather than a SQLite fallback.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import time
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]


def _database_url() -> str:
    value = os.environ.get("BILLING_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not value or not value.strip():
        raise RuntimeError("BILLING_TEST_DATABASE_URL or DATABASE_URL is required")
    if value.startswith("postgresql+asyncpg://"):
        return "postgresql://" + value.removeprefix("postgresql+asyncpg://")
    if not value.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("the concurrency gate requires a PostgreSQL URL")
    return value


async def _run(*, minimum_wait_ms: float) -> dict[str, object]:
    dsn = _database_url()
    table = f"release_concurrency_gate_{uuid4().hex}"
    first: asyncpg.Connection | None = None
    second: asyncpg.Connection | None = None
    blocked_update: asyncio.Task[float] | None = None
    try:
        first = await asyncpg.connect(dsn)
        second = await asyncpg.connect(dsn)
        await first.execute(
            f'CREATE TABLE "{table}" (id integer PRIMARY KEY, counter integer NOT NULL)'
        )
        await first.execute(f'INSERT INTO "{table}" (id, counter) VALUES (1, 0)')

        await first.execute("BEGIN")
        await first.execute(f'UPDATE "{table}" SET counter = counter + 1 WHERE id = 1')

        async def blocked_update_duration_ms() -> float:
            await second.execute("BEGIN")
            started = time.perf_counter()
            await second.execute(f'UPDATE "{table}" SET counter = counter + 1 WHERE id = 1')
            waited_ms = (time.perf_counter() - started) * 1000
            await second.execute("COMMIT")
            return waited_ms

        blocked_update = asyncio.create_task(blocked_update_duration_ms())
        await asyncio.sleep(0.2)
        if blocked_update.done():
            raise RuntimeError("the second PostgreSQL transaction did not block on the row lock")

        await first.execute("COMMIT")
        waited_ms = await blocked_update
        if waited_ms < minimum_wait_ms:
            raise RuntimeError("the PostgreSQL row-lock wait was shorter than the gate threshold")

        counter = await first.fetchval(f'SELECT counter FROM "{table}" WHERE id = 1')
        if counter != 2:
            raise RuntimeError("the PostgreSQL row-lock counter was not serialized")
        return {
            "status": "ok",
            "gate": "postgres-row-lock",
            "waited_ms": round(waited_ms, 1),
            "counter": counter,
        }
    finally:
        if blocked_update is not None and not blocked_update.done():
            blocked_update.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await blocked_update
        if second is not None:
            with contextlib.suppress(Exception):
                await second.execute("ROLLBACK")
        if first is not None:
            with contextlib.suppress(Exception):
                await first.execute("ROLLBACK")
            with contextlib.suppress(Exception):
                await first.execute(f'DROP TABLE IF EXISTS "{table}"')
        if second is not None:
            await second.close()
        if first is not None:
            await first.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the real PostgreSQL row-lock release gate")
    parser.add_argument("--minimum-wait-ms", type=float, default=50.0)
    args = parser.parse_args(argv)
    if args.minimum_wait_ms < 0:
        raise ValueError("--minimum-wait-ms must not be negative")
    try:
        result = asyncio.run(_run(minimum_wait_ms=args.minimum_wait_ms))
    except (OSError, RuntimeError, asyncpg.PostgresError) as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "gate": "postgres-row-lock",
                    "error_type": type(error).__name__,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
