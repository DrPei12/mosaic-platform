"""Integrity helpers for live provider evidence.

Live evidence is only useful for activation when it is tied to the source that
will consume it.  This module keeps the source binding and HMAC contract in one
place so the producer and activation path cannot silently drift apart.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .manifest import canonical_json_bytes, manifest_digest

LIVE_EVIDENCE_HMAC_KEY_ENV = "MOSAIC_LIVE_EVIDENCE_HMAC_KEY"
SOURCE_COMMIT_ENV = "MOSAIC_SOURCE_COMMIT"
SOURCE_TREE_CLEAN_ENV = "MOSAIC_SOURCE_TREE_CLEAN"
LIVE_EVIDENCE_HMAC_FIELD = "evidence_hmac_sha256"
MIN_HMAC_KEY_CHARS = 32
SOURCE_FACT_FIELDS = (
    "source_commit",
    "catalog_manifest_digest",
    "smoke_script_sha256",
    "source_tree_clean",
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER_MARKERS = ("replace_with", "placeholder")


class LiveEvidenceError(ValueError):
    """Raised when live evidence cannot be securely produced or validated."""


def _git_root(anchor: Path) -> Path:
    resolved = anchor.resolve()
    start = resolved if resolved.is_dir() else resolved.parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise LiveEvidenceError("source repository is unavailable")


def current_source_commit(anchor: Path) -> str:
    """Return the full commit identity for the repository containing ``anchor``."""

    injected = os.environ.get(SOURCE_COMMIT_ENV, "").strip().casefold()
    if injected:
        if _COMMIT_RE.fullmatch(injected) is None:
            raise LiveEvidenceError("injected source commit is invalid")
        return injected
    try:
        root = _git_root(anchor)
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise LiveEvidenceError("current source commit is unavailable") from error
    commit = result.stdout.strip()
    if _COMMIT_RE.fullmatch(commit) is None:
        raise LiveEvidenceError("current source commit is invalid")
    return commit


def source_tree_clean(anchor: Path) -> bool:
    """Return whether the source repository has no tracked or untracked changes."""

    injected = os.environ.get(SOURCE_TREE_CLEAN_ENV)
    if injected is not None:
        normalized = injected.strip().casefold()
        if normalized not in {"true", "false"}:
            raise LiveEvidenceError("injected source tree state is invalid")
        return normalized == "true"
    try:
        root = _git_root(anchor)
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise LiveEvidenceError("source tree status is unavailable") from error
    return result.stdout == ""


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest of a file's exact bytes."""

    try:
        return hashlib.sha256(path.resolve().read_bytes()).hexdigest()
    except OSError as error:
        raise LiveEvidenceError("smoke script digest is unavailable") from error


def current_live_evidence_facts(smoke_script_path: Path) -> dict[str, Any]:
    """Collect the source facts an activation consumer must match."""

    smoke_script = smoke_script_path.resolve()
    if not smoke_script.is_file():
        raise LiveEvidenceError("smoke script is unavailable")
    if not source_tree_clean(smoke_script):
        raise LiveEvidenceError("source tree must be clean for live evidence")
    return {
        "source_commit": current_source_commit(smoke_script),
        "catalog_manifest_digest": manifest_digest(),
        "smoke_script_sha256": sha256_file(smoke_script),
        "source_tree_clean": True,
    }


def _hmac_key(key: bytes | str | None = None) -> bytes:
    def validate_text(value: str) -> bytes:
        normalized = value.strip()
        if len(normalized) < MIN_HMAC_KEY_CHARS:
            raise LiveEvidenceError(
                f"{LIVE_EVIDENCE_HMAC_KEY_ENV} must be at least {MIN_HMAC_KEY_CHARS} characters"
            )
        if any(marker in normalized.casefold() for marker in _PLACEHOLDER_MARKERS):
            raise LiveEvidenceError(
                f"{LIVE_EVIDENCE_HMAC_KEY_ENV} must not use an example placeholder"
            )
        return normalized.encode("utf-8")

    if key is None:
        value = os.environ.get(LIVE_EVIDENCE_HMAC_KEY_ENV)
        if value is None:
            raise LiveEvidenceError(f"{LIVE_EVIDENCE_HMAC_KEY_ENV} is required for live evidence")
        return validate_text(value)
    if isinstance(key, str):
        return validate_text(key)
    if len(key) < MIN_HMAC_KEY_CHARS:
        raise LiveEvidenceError(
            f"{LIVE_EVIDENCE_HMAC_KEY_ENV} must be at least {MIN_HMAC_KEY_CHARS} characters"
        )
    return key


def live_evidence_hmac_key() -> bytes:
    """Read and validate the signing key without exposing it to callers."""

    return _hmac_key()


def _unsigned_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise LiveEvidenceError("live evidence must be an object")
    return {key: value for key, value in evidence.items() if key != LIVE_EVIDENCE_HMAC_FIELD}


def evidence_hmac_sha256(evidence: Mapping[str, Any], *, key: bytes | str | None = None) -> str:
    """Compute the HMAC over canonical evidence with its signature omitted."""

    try:
        payload = canonical_json_bytes(_unsigned_evidence(evidence))
    except (TypeError, ValueError) as error:
        raise LiveEvidenceError("live evidence is not canonically serializable") from error
    return hmac.new(_hmac_key(key), payload, hashlib.sha256).hexdigest()


def bind_live_evidence(
    evidence: Mapping[str, Any],
    *,
    smoke_script_path: Path,
    key: bytes | str | None = None,
) -> dict[str, Any]:
    """Attach current source facts and an HMAC to an evidence object."""

    bound = dict(evidence)
    bound.update(current_live_evidence_facts(smoke_script_path))
    bound[LIVE_EVIDENCE_HMAC_FIELD] = evidence_hmac_sha256(bound, key=key)
    return bound


def verify_live_evidence_integrity(evidence: Mapping[str, Any], *, smoke_script_path: Path) -> None:
    """Require current source facts and a valid HMAC for activation."""

    if not isinstance(evidence, Mapping):
        raise LiveEvidenceError("live evidence must be an object")
    expected_facts = current_live_evidence_facts(smoke_script_path)
    for field in SOURCE_FACT_FIELDS:
        actual = evidence.get(field)
        expected = expected_facts[field]
        if field == "source_tree_clean":
            if actual is not True or expected is not True:
                raise LiveEvidenceError("live evidence source tree is not clean")
            continue
        if not isinstance(actual, str) or not hmac.compare_digest(actual, expected):
            raise LiveEvidenceError(f"live evidence {field} does not match current source")

    actual_hmac = evidence.get(LIVE_EVIDENCE_HMAC_FIELD)
    if not isinstance(actual_hmac, str) or _SHA256_RE.fullmatch(actual_hmac) is None:
        raise LiveEvidenceError("live evidence HMAC is invalid")
    expected_hmac = evidence_hmac_sha256(evidence)
    if not hmac.compare_digest(actual_hmac, expected_hmac):
        raise LiveEvidenceError("live evidence HMAC does not match")


__all__ = [
    "LIVE_EVIDENCE_HMAC_FIELD",
    "LIVE_EVIDENCE_HMAC_KEY_ENV",
    "MIN_HMAC_KEY_CHARS",
    "SOURCE_COMMIT_ENV",
    "SOURCE_FACT_FIELDS",
    "SOURCE_TREE_CLEAN_ENV",
    "LiveEvidenceError",
    "bind_live_evidence",
    "current_live_evidence_facts",
    "current_source_commit",
    "evidence_hmac_sha256",
    "live_evidence_hmac_key",
    "sha256_file",
    "source_tree_clean",
    "verify_live_evidence_integrity",
]
