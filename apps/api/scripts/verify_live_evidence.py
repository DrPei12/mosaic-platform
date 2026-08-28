"""Verify signed Provider evidence without mutating catalog state."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.seed_product_catalog import validate_activation_evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify MOSAIC live Provider evidence")
    parser.add_argument("evidence_file", type=Path)
    return parser


def verify(path: Path) -> dict[str, object]:
    payload_bytes = path.read_bytes()
    payload = json.loads(payload_bytes)
    if not isinstance(payload, Mapping):
        raise TypeError("live evidence JSON must be an object")
    validate_activation_evidence(payload)
    checks = payload.get("checks")
    if not isinstance(checks, list):
        raise TypeError("live evidence checks must be an array")
    modalities = sorted(
        str(item["modality"])
        for item in checks
        if isinstance(item, Mapping) and isinstance(item.get("modality"), str)
    )
    return {
        "status": "ok",
        "source_commit": str(payload["source_commit"]),
        "completed_at": str(payload["completed_at"]),
        "modalities": modalities,
        "evidence_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "secrets_exposed": False,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify(args.evidence_file)
    except (OSError, TypeError, ValueError) as error:
        print(f"live evidence verification failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "verify"]
