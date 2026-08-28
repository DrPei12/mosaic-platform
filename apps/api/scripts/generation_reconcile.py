"""List and resolve generation outcomes through audited operator actions."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.generations.recovery import GenerationRecoveryService
from app.infrastructure.database import dispose_engine, session_factory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MOSAIC generation reconciliation")
    subcommands = parser.add_subparsers(dest="command", required=True)
    listing = subcommands.add_parser("list")
    listing.add_argument("--limit", type=int, default=50)
    resolve = subcommands.add_parser("resolve-failed")
    resolve.add_argument("--tenant-id", type=UUID, required=True)
    resolve.add_argument("--job-id", type=UUID, required=True)
    resolve.add_argument("--reason", required=True)
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    service = GenerationRecoveryService(session_factory)
    if args.command == "list":
        rows = await service.list_pending(limit=args.limit)
        return {
            "status": "ok",
            "items": [
                {
                    "tenant_id": str(row.tenant_id),
                    "job_id": str(row.job_id),
                    "modality": row.modality,
                    "provider_request_id_present": row.provider_request_id is not None,
                    "provider_task_id_present": row.provider_task_id is not None,
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ],
        }
    subject = os.environ.get("MOSAIC_OPERATOR_SUBJECT", "").strip()
    if not subject:
        raise RuntimeError("MOSAIC_OPERATOR_SUBJECT is required")
    await service.resolve_failed(
        tenant_id=args.tenant_id,
        job_id=args.job_id,
        operator_subject=subject,
        reason=args.reason,
    )
    return {"status": "ok", "job_id": str(args.job_id), "outcome": "failed"}


async def _run_and_dispose(args: argparse.Namespace) -> dict[str, object]:
    try:
        return await _run(args)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(_run_and_dispose(args))
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # noqa: BLE001 - operator CLI emits only a safe error type
        print(
            json.dumps(
                {"status": "failed", "error_type": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
