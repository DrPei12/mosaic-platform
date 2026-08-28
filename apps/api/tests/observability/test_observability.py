from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

import app.api.metrics as metrics_api
import app.observability.server as metrics_server
from app.core.settings import Settings
from app.main import create_app
from app.observability.logging import JsonLogFormatter
from app.observability.metrics import (
    REGISTRY,
    MetricDefinition,
    metrics_text,
    record_dependency_ready,
    record_http_request,
    record_worker_outcome,
)


@pytest.fixture(autouse=True)
def clean_metrics() -> None:
    REGISTRY.reset()
    REGISTRY.set("mosaic_sse_active_connections", 0)
    yield
    REGISTRY.reset()
    REGISTRY.set("mosaic_sse_active_connections", 0)


def test_metric_definitions_reject_identifier_labels_and_values() -> None:
    with pytest.raises(ValueError, match="bounded"):
        MetricDefinition("test_metric_total", "test", "counter", ("tenant_id",))

    with pytest.raises(ValueError, match="identifiers"):
        REGISTRY.inc(
            "mosaic_http_requests_total",
            labels={
                "method": "GET",
                "route": f"/api/v1/jobs/{uuid4()}",
                "status_code": "200",
            },
        )


def test_http_metrics_normalize_path_parameters_and_keep_labels_bounded() -> None:
    identifier = uuid4()
    record_http_request(
        method="GET",
        path=f"/api/v1/generations/{identifier}/artifacts/{identifier}",
        status_code=200,
        duration_seconds=0.125,
    )

    rendered = metrics_text()
    assert str(identifier) not in rendered
    assert 'route="/api/v1/generations/{id}/artifacts/{id}"' in rendered
    assert 'status_code="200"' in rendered
    assert "mosaic_http_request_duration_seconds_bucket" in rendered


def test_worker_metric_labels_are_fixed_and_do_not_include_job_identity() -> None:
    record_worker_outcome(worker="generation_media", outcome="success")
    record_worker_outcome(worker="generation_video", outcome="submitted_unknown")

    rendered = metrics_text()
    assert 'worker="generation_media"' in rendered
    assert 'worker="generation_video"' in rendered
    assert "tenant_id" not in rendered
    assert "job_id" not in rendered
    assert "request_id" not in rendered


def test_generation_dependency_metric_labels_are_fixed_and_separate() -> None:
    record_dependency_ready(dependency="session_token_codec", ready=True)
    record_dependency_ready(dependency="generation_media_worker", ready=True)
    record_dependency_ready(dependency="generation_video_worker", ready=False)
    record_dependency_ready(dependency="generation_worker", ready=False)

    rendered = metrics_text()
    assert 'dependency="session_token_codec"} 1' in rendered
    assert 'dependency="generation_media_worker"} 1' in rendered
    assert 'dependency="generation_video_worker"} 0' in rendered
    assert 'dependency="generation_worker"} 0' in rendered
    assert "media-worker-id" not in rendered
    assert "video-worker-id" not in rendered


def test_json_logs_include_required_fields_and_drop_sensitive_fields() -> None:
    token = "provider-secret-token"
    record = logging.LogRecord(
        name="mosaic",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="this message must not be serialized: %s",
        args=(token,),
        exc_info=None,
    )
    record.mosaic_event = "test.safe.event"  # type: ignore[attr-defined]
    record.mosaic_fields = {  # type: ignore[attr-defined]
        "route": "/api/v1/health/live",
        "status_code": 200,
        "cookie": "session-cookie",
        "password": "password-value",
        "token": token,
        "provider_url": "https://provider.example/secret",
        "body": "prompt or response body",
    }

    rendered = JsonLogFormatter(service="mosaic-api", version="9.9.9").format(record)
    payload = json.loads(rendered)
    assert {"request_id", "service", "version", "level", "event"} <= set(payload)
    assert payload["request_id"] == "system"
    assert payload["event"] == "test.safe.event"
    for secret in (
        "session-cookie",
        "password-value",
        token,
        "https://provider.example/secret",
        "prompt or response body",
    ):
        assert secret not in rendered


@pytest.mark.asyncio
async def test_api_metrics_is_internal_token_protected_and_not_public() -> None:
    original = metrics_api.settings
    metrics_api.settings = Settings(
        _env_file=None,
        metrics_enabled=True,
        metrics_internal_token=SecretStr("metrics-secret"),
    )
    try:
        app = create_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            assert (await client.get("/metrics")).status_code == 404
            assert (await client.get("/api/v1/metrics")).status_code == 404
            assert (await client.get("/internal/metrics")).status_code == 404
            assert (
                await client.get(
                    "/internal/metrics",
                    headers={"x-mosaic-metrics-token": "wrong"},
                )
            ).status_code == 404
            response = await client.get(
                "/internal/metrics",
                headers={"x-mosaic-metrics-token": "metrics-secret"},
            )
    finally:
        metrics_api.settings = original

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "# TYPE mosaic_http_requests_total counter" in response.text
    assert "metrics-secret" not in response.text


@pytest.mark.asyncio
async def test_api_metrics_can_be_disabled() -> None:
    original = metrics_api.settings
    metrics_api.settings = Settings(_env_file=None, metrics_enabled=False)
    try:
        app = create_app()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/internal/metrics")
    finally:
        metrics_api.settings = original

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_metrics_listener_serves_only_internal_path_and_can_be_stopped() -> None:
    original = metrics_server.settings
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = int(probe.getsockname()[1])
    metrics_server.settings = Settings(
        _env_file=None,
        metrics_enabled=True,
        metrics_server_enabled=True,
        metrics_bind_host="127.0.0.1",
        metrics_port=free_port,
        metrics_internal_token=SecretStr("listener-secret"),
    )
    server = await metrics_server.start_internal_metrics_server()
    assert server is not None
    port = server.sockets[0].getsockname()[1]

    async def request(path: str, token: str | None = None) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        header = f"X-Mosaic-Metrics-Token: {token}\r\n" if token else ""
        writer.write(
            f"GET {path} HTTP/1.1\r\nHost: test\r\n{header}Connection: close\r\n\r\n".encode(
                "ascii"
            )
        )
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()
        return response

    try:
        assert b"404 Not Found" in await request("/metrics", "listener-secret")
        assert b"404 Not Found" in await request("/internal/metrics")
        response = await request("/internal/metrics", "listener-secret")
    finally:
        await metrics_server.stop_internal_metrics_server(server)
        metrics_server.settings = original

    assert b"200 OK" in response
    assert b"# TYPE mosaic_http_requests_total counter" in response
    assert b"listener-secret" not in response


def test_compose_keeps_api_host_port_closed_and_worker_metrics_internal() -> None:
    compose = (
        Path(__file__).parents[4] / "infra" / "compose" / "docker-compose.production.yml"
    ).read_text(encoding="utf-8")
    api_block = re.search(
        r"\n  api:\n(?P<body>.*?)(?=\n  [a-z-]+:\n|\Z)",
        compose,
        re.DOTALL,
    )
    assert api_block is not None
    assert "ports:" not in api_block.group("body")
    assert 'expose:\n      - "8000"' in api_block.group("body")
    for service in ("chat-relay", "generation-relay", "chat-worker", "image-audio-worker", "video-worker"):
        service_block = re.search(
            rf"\n  {service}:\n(?P<body>.*?)(?=\n  [a-z-]+:\n|\Z)",
            compose,
            re.DOTALL,
        )
        assert service_block is not None
        assert "ports:" not in service_block.group("body")
        assert 'expose:\n      - "9090"' in service_block.group("body")
