"""Delete expired generation objects without deleting financial history."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import settings
from app.generations.lifecycle import ArtifactCleanupService
from app.generations.storage import build_artifact_storage
from app.infrastructure.database import dispose_engine, session_factory


async def _run(*, watch: bool, interval_seconds: float) -> None:
    cleanup = ArtifactCleanupService(session_factory, build_artifact_storage(settings))
    while True:
        processed = await cleanup.run_once()
        if not watch:
            return
        if not processed:
            await asyncio.sleep(interval_seconds)


async def _run_and_dispose(*, watch: bool, interval_seconds: float) -> None:
    try:
        await _run(watch=watch, interval_seconds=interval_seconds)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MOSAIC artifact cleanup")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    if args.interval_seconds <= 0:
        raise ValueError("cleanup interval must be positive")
    try:
        asyncio.run(
            _run_and_dispose(
                watch=args.watch,
                interval_seconds=args.interval_seconds,
            )
        )
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
