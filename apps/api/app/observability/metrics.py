"""Small dependency-free Prometheus exposition and low-cardinality helpers."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

MetricKind = Literal["counter", "gauge", "histogram"]
LabelPolicy = Callable[[str], bool]

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_UUID_RE = re.compile(
    r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])"
)
_HTTP_STATUS_RE = re.compile(r"^[1-5][0-9]{2}$")
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_EVENT_TYPES = frozenset(
    {
        "chat.inference.execute",
        "generation.accepted",
        "generation.video.accepted",
        "other",
    }
)
_WORKERS = frozenset({"chat", "generation_media", "generation_video", "other"})
_REDIS_RESOURCES = frozenset(
    {"chat_stream_global", "chat_stream_tenant", "deployment", "tenant_deployment", "other"}
)
_DEPENDENCIES = frozenset(
    {
        "database",
        "redis",
        "provider",
        "session_token_codec",
        "chat_worker",
        "chat_relay",
        "generation_media_worker",
        "generation_video_worker",
        "generation_worker",
        "generation_relay",
        "chat_stack",
        "generation_stack",
        "api",
        "other",
    }
)
_REPLAY_REASONS = frozenset({"subscription_open", "subscription_wait", "notification_loss", "other"})
_ARTIFACT_DIRECTIONS = frozenset({"read", "write", "other"})
_ARTIFACT_OPERATIONS = frozenset({"open_stream", "put_bytes", "transfer_remote", "other"})
_INVARIANTS = frozenset({"wallet", "reservation", "currency", "usage", "other"})
_ALLOWED_LABEL_NAMES = frozenset(
    {
        "method",
        "route",
        "status_code",
        "dependency",
        "event_type",
        "worker",
        "resource",
        "reason",
        "direction",
        "operation",
        "invariant",
        "outcome",
    }
)


def _one_of(values: frozenset[str]) -> LabelPolicy:
    return lambda value: value in values


def _route_policy(value: str) -> bool:
    return bool(re.fullmatch(r"/[a-z0-9_{}./-]{1,159}", value))


def _status_policy(value: str) -> bool:
    return _HTTP_STATUS_RE.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    name: str
    help: str
    kind: MetricKind
    labels: tuple[str, ...] = ()
    buckets: tuple[float, ...] = ()
    policies: Mapping[str, LabelPolicy] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if _NAME_RE.fullmatch(self.name) is None:
            raise ValueError("metric name is invalid")
        if not self.help.strip():
            raise ValueError("metric help must not be blank")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("metric labels must be unique")
        if set(self.labels) - _ALLOWED_LABEL_NAMES:
            raise ValueError("metric labels must use bounded names")
        forbidden = ("tenant", "job", "request", "id")
        if any(any(part in label.lower() for part in forbidden) for label in self.labels):
            raise ValueError("metrics must not use tenant, job, request or id labels")
        if set(self.policies) - set(self.labels):
            raise ValueError("metric policy has an unknown label")
        if self.kind == "histogram":
            if not self.buckets or tuple(sorted(set(self.buckets))) != self.buckets:
                raise ValueError("histogram buckets must be sorted and non-empty")
            if any(not math.isfinite(bucket) or bucket <= 0 for bucket in self.buckets):
                raise ValueError("histogram buckets must be positive and finite")


@dataclass(slots=True)
class _HistogramValue:
    counts: list[int]
    total: float = 0.0


class MetricsRegistry:
    """Thread-safe in-process registry with static metric definitions."""

    def __init__(self, definitions: Sequence[MetricDefinition]) -> None:
        self._definitions = tuple(definitions)
        self._by_name = {definition.name: definition for definition in self._definitions}
        if len(self._by_name) != len(self._definitions):
            raise ValueError("metric names must be unique")
        self._values: dict[str, dict[tuple[str, ...], float | _HistogramValue]] = {
            definition.name: {} for definition in self._definitions
        }
        self._lock = Lock()

    def inc(
        self,
        name: str,
        amount: float = 1,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        definition, key = self._validated(name, labels)
        if definition.kind not in {"counter", "gauge"}:
            raise TypeError("inc is only valid for counters and gauges")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise TypeError("metric amount must be numeric")
        if not math.isfinite(float(amount)):
            raise ValueError("metric amount must be finite")
        if definition.kind == "counter" and amount < 0:
            raise ValueError("counter amount must not be negative")
        with self._lock:
            current = self._values[name].get(key, 0.0)
            if not isinstance(current, (int, float)):
                raise TypeError("metric value kind mismatch")
            self._values[name][key] = float(current) + float(amount)

    def add_gauge(
        self,
        name: str,
        amount: float,
        *,
        labels: Mapping[str, str] | None = None,
        minimum: float | None = None,
    ) -> None:
        definition, key = self._validated(name, labels)
        if definition.kind != "gauge":
            raise TypeError("add_gauge requires a gauge")
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise TypeError("metric amount must be numeric")
        if not math.isfinite(float(amount)):
            raise ValueError("metric amount must be finite")
        with self._lock:
            current = self._values[name].get(key, 0.0)
            if not isinstance(current, (int, float)):
                raise TypeError("metric value kind mismatch")
            value = float(current) + float(amount)
            if minimum is not None:
                value = max(value, minimum)
            self._values[name][key] = value

    def set(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        definition, key = self._validated(name, labels)
        if definition.kind != "gauge":
            raise TypeError("set requires a gauge")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError("metric value must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError("metric value must be finite")
        with self._lock:
            self._values[name][key] = float(value)

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        definition, key = self._validated(name, labels)
        if definition.kind != "histogram":
            raise TypeError("observe requires a histogram")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError("observation must be numeric")
        if not math.isfinite(float(value)) or value < 0:
            raise ValueError("observation must be finite and non-negative")
        with self._lock:
            current = self._values[name].get(key)
            if current is None:
                current = _HistogramValue(counts=[0] * (len(definition.buckets) + 1))
                self._values[name][key] = current
            if not isinstance(current, _HistogramValue):
                raise TypeError("metric value kind mismatch")
            for index, bucket in enumerate(definition.buckets):
                if value <= bucket:
                    current.counts[index] += 1
                    break
            else:
                current.counts[-1] += 1
            current.total += float(value)

    def reset(self) -> None:
        with self._lock:
            for values in self._values.values():
                values.clear()

    def render(self) -> str:
        with self._lock:
            snapshots: dict[str, dict[tuple[str, ...], float | _HistogramValue]] = {}
            for name, values in self._values.items():
                snapshots[name] = {
                    key: (
                        _HistogramValue(counts=list(value.counts), total=value.total)
                        if isinstance(value, _HistogramValue)
                        else value
                    )
                    for key, value in values.items()
                }
        lines: list[str] = []
        for definition in self._definitions:
            lines.append(f"# HELP {definition.name} {definition.help}")
            lines.append(f"# TYPE {definition.name} {definition.kind}")
            values = snapshots[definition.name]
            for key, value in sorted(values.items()):
                labels = dict(zip(definition.labels, key, strict=True))
                if definition.kind == "histogram":
                    assert isinstance(value, _HistogramValue)
                    cumulative = 0
                    for index, bucket in enumerate(definition.buckets):
                        cumulative += value.counts[index]
                        lines.append(
                            _sample(
                                f"{definition.name}_bucket",
                                cumulative,
                                {**labels, "le": _number(bucket)},
                            )
                        )
                    cumulative += value.counts[-1]
                    lines.append(
                        _sample(
                            f"{definition.name}_bucket",
                            cumulative,
                            {**labels, "le": "+Inf"},
                        )
                    )
                    lines.append(_sample(f"{definition.name}_count", cumulative, labels))
                    lines.append(_sample(f"{definition.name}_sum", value.total, labels))
                else:
                    assert isinstance(value, (int, float))
                    lines.append(_sample(definition.name, value, labels))
        return "\n".join(lines) + "\n"

    def _validated(
        self,
        name: str,
        labels: Mapping[str, str] | None,
    ) -> tuple[MetricDefinition, tuple[str, ...]]:
        try:
            definition = self._by_name[name]
        except KeyError:
            raise KeyError(f"unknown metric: {name}") from None
        supplied = dict(labels or {})
        if set(supplied) != set(definition.labels):
            raise ValueError(f"labels for {name} must be {definition.labels}")
        result: list[str] = []
        for label in definition.labels:
            value = supplied[label]
            if not isinstance(value, str) or not value or len(value) > 160:
                raise ValueError("metric label values must be short non-empty strings")
            if _UUID_RE.search(value):
                raise ValueError("metric labels must not contain identifiers")
            policy = definition.policies.get(label)
            if policy is not None and not policy(value):
                raise ValueError(f"invalid value for metric label: {label}")
            result.append(value)
        return definition, tuple(result)


def _number(value: float) -> str:
    return format(value, ".15g")


def _sample(name: str, value: float, labels: Mapping[str, str]) -> str:
    suffix = ""
    if labels:
        encoded = ",".join(
            f'{key}="{raw.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34)).replace(chr(10), chr(92) + "n")}"'
            for key, raw in sorted(labels.items())
        )
        suffix = "{" + encoded + "}"
    return f"{name}{suffix} {_number(float(value))}"


_DEFINITIONS = (
    MetricDefinition(
        "mosaic_http_requests_total",
        "Completed HTTP requests by normalized route and status.",
        "counter",
        ("method", "route", "status_code"),
        policies={"method": _one_of(_METHODS), "route": _route_policy, "status_code": _status_policy},
    ),
    MetricDefinition(
        "mosaic_http_request_duration_seconds",
        "HTTP request duration in seconds by normalized route and status.",
        "histogram",
        ("method", "route", "status_code"),
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
        policies={"method": _one_of(_METHODS), "route": _route_policy, "status_code": _status_policy},
    ),
    MetricDefinition("mosaic_db_pool_size", "Configured database pool size.", "gauge"),
    MetricDefinition("mosaic_db_pool_checked_out", "Database connections currently checked out.", "gauge"),
    MetricDefinition("mosaic_db_pool_checked_in", "Database connections currently checked in.", "gauge"),
    MetricDefinition("mosaic_db_pool_overflow", "Database pool overflow connections currently in use.", "gauge"),
    MetricDefinition("mosaic_db_pool_timeouts_total", "Database pool checkout timeouts.", "counter"),
    MetricDefinition(
        "mosaic_dependency_ready",
        "Whether a named runtime dependency is ready.",
        "gauge",
        ("dependency",),
        policies={"dependency": _one_of(_DEPENDENCIES)},
    ),
    MetricDefinition(
        "mosaic_outbox_claimed_total",
        "Outbox events claimed by the relay.",
        "counter",
        ("event_type",),
        policies={"event_type": _one_of(_EVENT_TYPES)},
    ),
    MetricDefinition(
        "mosaic_outbox_published_total",
        "Outbox events successfully published and fenced-marked.",
        "counter",
        ("event_type",),
        policies={"event_type": _one_of(_EVENT_TYPES)},
    ),
    MetricDefinition(
        "mosaic_outbox_retry_total",
        "Outbox events scheduled for another delivery attempt.",
        "counter",
        ("event_type",),
        policies={"event_type": _one_of(_EVENT_TYPES)},
    ),
    MetricDefinition(
        "mosaic_outbox_fenced_total",
        "Outbox events rejected by lease-token fencing.",
        "counter",
        ("event_type",),
        policies={"event_type": _one_of(_EVENT_TYPES)},
    ),
    MetricDefinition(
        "mosaic_outbox_failed_total",
        "Outbox events that reached a terminal relay failure.",
        "counter",
        ("event_type",),
        policies={"event_type": _one_of(_EVENT_TYPES)},
    ),
    MetricDefinition(
        "mosaic_worker_success_total",
        "Worker executions completed successfully.",
        "counter",
        ("worker",),
        policies={"worker": _one_of(_WORKERS)},
    ),
    MetricDefinition(
        "mosaic_worker_failure_total",
        "Worker executions that failed without an uncertain submission.",
        "counter",
        ("worker",),
        policies={"worker": _one_of(_WORKERS)},
    ),
    MetricDefinition(
        "mosaic_worker_submitted_unknown_total",
        "Worker executions requiring uncertain-submission reconciliation.",
        "counter",
        ("worker",),
        policies={"worker": _one_of(_WORKERS)},
    ),
    MetricDefinition(
        "mosaic_redis_permit_saturation_total",
        "Redis permit acquisitions rejected because the configured limit was full.",
        "counter",
        ("resource",),
        policies={"resource": _one_of(_REDIS_RESOURCES)},
    ),
    MetricDefinition(
        "mosaic_redis_permit_loss_total",
        "Redis permit renewal or release losses.",
        "counter",
        ("resource",),
        policies={"resource": _one_of(_REDIS_RESOURCES)},
    ),
    MetricDefinition(
        "mosaic_redis_notification_loss_total",
        "Redis stream wake-up notifications lost or unavailable.",
        "counter",
    ),
    MetricDefinition("mosaic_sse_active_connections", "Active server-sent event connections.", "gauge"),
    MetricDefinition(
        "mosaic_sse_replay_fallback_total",
        "SSE connections using bounded database replay fallback.",
        "counter",
        ("reason",),
        policies={"reason": _one_of(_REPLAY_REASONS)},
    ),
    MetricDefinition("mosaic_billing_hold_total", "Billing hold operations observed.", "counter"),
    MetricDefinition("mosaic_billing_capture_total", "Billing capture operations observed.", "counter"),
    MetricDefinition("mosaic_billing_release_total", "Billing release operations observed.", "counter"),
    MetricDefinition(
        "mosaic_billing_invariant_total",
        "Billing invariant violations observed.",
        "counter",
        ("invariant",),
        policies={"invariant": _one_of(_INVARIANTS)},
    ),
    MetricDefinition(
        "mosaic_artifact_transfer_bytes_total",
        "Artifact bytes transferred across the storage boundary.",
        "counter",
        ("direction",),
        policies={"direction": _one_of(_ARTIFACT_DIRECTIONS)},
    ),
    MetricDefinition(
        "mosaic_artifact_transfer_failures_total",
        "Artifact storage transfer failures.",
        "counter",
        ("direction", "operation"),
        policies={
            "direction": _one_of(_ARTIFACT_DIRECTIONS),
            "operation": _one_of(_ARTIFACT_OPERATIONS),
        },
    ),
    MetricDefinition(
        "mosaic_metrics_scrapes_total",
        "Internal metrics endpoint requests by outcome.",
        "counter",
        ("outcome",),
        policies={"outcome": _one_of(frozenset({"success", "denied", "disabled", "other"}))},
    ),
)

REGISTRY = MetricsRegistry(_DEFINITIONS)
REGISTRY.set("mosaic_sse_active_connections", 0)


def normalize_route(path: str) -> str:
    """Return a bounded route label with no raw path parameters."""

    known = frozenset(
        {
            "api",
            "v1",
            "health",
            "live",
            "ready",
            "internal",
            "metrics",
            "auth",
            "me",
            "login",
            "logout",
            "password",
            "change",
            "sessions",
            "register",
            "models",
            "conversations",
            "messages",
            "requests",
            "resume",
            "regenerate",
            "stop",
            "generations",
            "artifacts",
            "usage",
        }
    )
    if not isinstance(path, str) or not path.startswith("/"):
        return "/other"
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "/"
    normalized: list[str] = []
    for part in parts[:12]:
        if part in {"{id}", "{param}"}:
            normalized.append(part)
        elif _UUID_RE.fullmatch(part) or part.isdigit():
            normalized.append("{id}")
        elif part in known:
            normalized.append(part)
        else:
            normalized.append("{param}")
    return "/" + "/".join(normalized)


def record_http_request(*, method: str, path: str, status_code: int, duration_seconds: float) -> None:
    method_label = method.upper() if method.upper() in _METHODS else "OTHER"
    status_label = str(status_code) if _HTTP_STATUS_RE.fullmatch(str(status_code)) else "500"
    labels = {"method": method_label, "route": normalize_route(path), "status_code": status_label}
    REGISTRY.inc("mosaic_http_requests_total", labels=labels)
    REGISTRY.observe("mosaic_http_request_duration_seconds", duration_seconds, labels=labels)


def record_dependency_ready(*, dependency: str, ready: bool) -> None:
    label = dependency if dependency in _DEPENDENCIES else "other"
    REGISTRY.set("mosaic_dependency_ready", 1 if ready else 0, labels={"dependency": label})


def record_db_pool_timeout() -> None:
    REGISTRY.inc("mosaic_db_pool_timeouts_total")


def record_outbox_outcome(*, event_type: str, outcome: str) -> None:
    event_label = event_type if event_type in _EVENT_TYPES else "other"
    metric_by_outcome = {
        "claimed": "mosaic_outbox_claimed_total",
        "published": "mosaic_outbox_published_total",
        "retry": "mosaic_outbox_retry_total",
        "fenced": "mosaic_outbox_fenced_total",
        "failed": "mosaic_outbox_failed_total",
    }
    metric = metric_by_outcome.get(outcome)
    if metric is not None:
        REGISTRY.inc(metric, labels={"event_type": event_label})


def record_worker_outcome(*, worker: str, outcome: str) -> None:
    worker_label = worker if worker in _WORKERS else "other"
    metric_by_outcome = {
        "success": "mosaic_worker_success_total",
        "failure": "mosaic_worker_failure_total",
        "submitted_unknown": "mosaic_worker_submitted_unknown_total",
    }
    metric = metric_by_outcome.get(outcome)
    if metric is not None:
        REGISTRY.inc(metric, labels={"worker": worker_label})


def redis_resource_label(resource: str) -> str:
    if resource == "chat-stream:global":
        return "chat_stream_global"
    if resource == "chat-stream:tenant" or resource.startswith("chat-stream:tenant:"):
        return "chat_stream_tenant"
    if resource == "deployment" or resource.startswith("deployment:"):
        return "deployment"
    if resource == "tenant_deployment" or resource.startswith("tenant:"):
        return "tenant_deployment"
    return "other"


def record_redis_permit_outcome(*, resource: str, outcome: str) -> None:
    metric = {
        "saturation": "mosaic_redis_permit_saturation_total",
        "loss": "mosaic_redis_permit_loss_total",
    }.get(outcome)
    if metric is not None:
        REGISTRY.inc(metric, labels={"resource": redis_resource_label(resource)})


def record_redis_notification_loss() -> None:
    REGISTRY.inc("mosaic_redis_notification_loss_total")


def set_sse_active(delta: int) -> None:
    REGISTRY.add_gauge("mosaic_sse_active_connections", delta, minimum=0)


def record_sse_replay_fallback(*, reason: str) -> None:
    label = reason if reason in _REPLAY_REASONS else "other"
    REGISTRY.inc("mosaic_sse_replay_fallback_total", labels={"reason": label})


def record_billing_operation(*, operation: str) -> None:
    metric = {
        "hold": "mosaic_billing_hold_total",
        "capture": "mosaic_billing_capture_total",
        "release": "mosaic_billing_release_total",
    }.get(operation)
    if metric is not None:
        REGISTRY.inc(metric)


def record_billing_invariant(*, invariant: str = "other") -> None:
    label = invariant if invariant in _INVARIANTS else "other"
    REGISTRY.inc("mosaic_billing_invariant_total", labels={"invariant": label})


def record_artifact_transfer(*, direction: str, byte_count: int) -> None:
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
        return
    label = direction if direction in _ARTIFACT_DIRECTIONS else "other"
    REGISTRY.inc("mosaic_artifact_transfer_bytes_total", byte_count, labels={"direction": label})


def record_artifact_failure(*, direction: str, operation: str) -> None:
    direction_label = direction if direction in _ARTIFACT_DIRECTIONS else "other"
    operation_label = operation if operation in _ARTIFACT_OPERATIONS else "other"
    REGISTRY.inc(
        "mosaic_artifact_transfer_failures_total",
        labels={"direction": direction_label, "operation": operation_label},
    )


def record_metrics_scrape(*, outcome: str) -> None:
    label = outcome if outcome in {"success", "denied", "disabled", "other"} else "other"
    REGISTRY.inc("mosaic_metrics_scrapes_total", labels={"outcome": label})


def metrics_text() -> str:
    return REGISTRY.render()


__all__ = [
    "REGISTRY",
    "MetricDefinition",
    "MetricsRegistry",
    "metrics_text",
    "normalize_route",
    "record_artifact_failure",
    "record_artifact_transfer",
    "record_billing_invariant",
    "record_billing_operation",
    "record_db_pool_timeout",
    "record_dependency_ready",
    "record_http_request",
    "record_metrics_scrape",
    "record_outbox_outcome",
    "record_redis_notification_loss",
    "record_redis_permit_outcome",
    "record_sse_replay_fallback",
    "record_worker_outcome",
    "redis_resource_label",
    "set_sse_active",
]
