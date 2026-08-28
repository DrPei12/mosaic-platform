"""Structured application logging with a deliberately small safe field set.

The formatter never serializes ``LogRecord.getMessage()`` or exception text.
Callers therefore cannot accidentally put request bodies, credentials, URLs or
provider responses into the application log by passing an unsafe value to a
logging call.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.request_id import current_request_id_or_system
from app.observability.metrics import normalize_route

_LOGGER_NAME = "mosaic"
_DEFAULT_SERVICE = "mosaic-api"
_EVENT_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(?:https?://|amqps?://|rediss?://|bearer\s+|password|secret|token|cookie|body)"
)
_SAFE_FIELDS = frozenset(
    {
        "method",
        "route",
        "status_code",
        "duration_ms",
        "dependency",
        "ready",
        "outcome",
        "reason",
        "error_code",
        "event_type",
        "worker",
        "queue",
        "operation",
        "direction",
        "bytes",
        "count",
        "configured",
    }
)


def _safe_scalar(value: object) -> str | int | float | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value[:200]
    return str(value)[:200]


def _safe_event(value: object) -> str:
    event = value if isinstance(value, str) else "invalid.event"
    return event if _EVENT_RE.fullmatch(event) is not None else "invalid.event"


def _safe_field(key: str, value: object) -> str | int | float | bool | None:
    if key == "route" and isinstance(value, str):
        return normalize_route(value)
    if isinstance(value, str) and _SENSITIVE_TEXT_RE.search(value):
        return None
    return _safe_scalar(value)


class JsonLogFormatter(logging.Formatter):
    """Render a log record as one JSON object without arbitrary extras."""

    def __init__(self, *, service: str, version: str) -> None:
        super().__init__()
        self.service = service
        self.version = version

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "request_id": current_request_id_or_system(),
            "service": self.service,
            "version": self.version,
            "level": record.levelname.lower(),
            "event": _safe_event(getattr(record, "mosaic_event", "log")),
        }
        fields = getattr(record, "mosaic_fields", {})
        if isinstance(fields, dict):
            for key, value in fields.items():
                if key in _SAFE_FIELDS:
                    safe_value = _safe_field(key, value)
                    if safe_value is not None:
                        payload[key] = safe_value
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def configure_logging(*, service: str = _DEFAULT_SERVICE, version: str) -> None:
    """Install one JSON stderr handler for application-owned log records."""

    logger = _logger()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in tuple(logger.handlers):
        if getattr(handler, "_mosaic_json_handler", False):
            handler.setFormatter(JsonLogFormatter(service=service, version=version))
            return
    handler = logging.StreamHandler(sys.stderr)
    handler._mosaic_json_handler = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonLogFormatter(service=service, version=version))
    logger.addHandler(handler)


def log_event(
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a safe event; unknown and sensitive fields are intentionally dropped."""

    safe_fields = {key: value for key, value in fields.items() if key in _SAFE_FIELDS}
    _logger().log(
        level,
        _safe_event(event),
        extra={"mosaic_event": _safe_event(event), "mosaic_fields": safe_fields},
    )


__all__ = ["JsonLogFormatter", "configure_logging", "log_event"]
