import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api.health import (
    chat_stack_ready,
    database_ready,
    generation_stack_ready,
    provider_ready,
    redis_ready,
    session_token_codec_ready,
)
from app.contracts.health import HealthResponse
from app.main import create_app


async def client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_live_returns_exact_contract_without_database_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.health as health_module

    async def fail_probe() -> bool:
        raise AssertionError("live must not probe dependencies")

    def fail_provider_probe() -> None:
        raise AssertionError("live must not inspect provider credentials")

    monkeypatch.setattr(health_module, "probe_database", fail_probe)
    monkeypatch.setattr(health_module, "probe_redis", fail_probe)
    monkeypatch.setattr(health_module.ProviderCredential, "from_env", fail_provider_probe)
    app = create_app()

    async for client in client_for(app):
        response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"service": "mosaic-api", "status": "ok", "version": "0.1.0"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "database_value",
        "redis_value",
        "provider_value",
        "session_token_value",
        "generation_value",
        "chat_value",
        "status_code",
    ),
    [
        (True, True, True, True, True, True, 200),
        (False, True, True, True, True, True, 503),
        (True, False, True, True, True, True, 503),
        (True, True, False, True, True, True, 503),
        (True, True, True, False, True, True, 503),
        (True, True, True, True, False, True, 503),
        (True, True, True, True, True, False, 503),
    ],
)
async def test_ready_requires_all_configured_dependencies(
    database_value: bool,
    redis_value: bool,
    provider_value: bool,
    session_token_value: bool,
    generation_value: bool,
    chat_value: bool,
    status_code: int,
) -> None:
    app = create_app()
    app.dependency_overrides[database_ready] = lambda: database_value
    app.dependency_overrides[redis_ready] = lambda: redis_value
    app.dependency_overrides[provider_ready] = lambda: provider_value
    app.dependency_overrides[session_token_codec_ready] = lambda: session_token_value
    app.dependency_overrides[generation_stack_ready] = lambda: generation_value
    app.dependency_overrides[chat_stack_ready] = lambda: chat_value

    async for client in client_for(app):
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == status_code
    if status_code == 200:
        assert response.json() == {"service": "mosaic-api", "status": "ready", "version": "0.1.0"}
    else:
        body = response.json()
        assert body["error"]["code"] == "SERVICE_DEPENDENCY_NOT_READY"
        assert body["error"]["retryable"] is True
        assert "postgresql" not in str(body).lower()
        assert "database_url" not in str(body).lower()


def test_openapi_exposes_health_paths_and_unavailable_ready_model() -> None:
    schema = create_app().openapi()

    assert "/api/v1/health/live" in schema["paths"]
    assert "/api/v1/health/ready" in schema["paths"]
    ready_responses = schema["paths"]["/api/v1/health/ready"]["get"]["responses"]
    assert "503" in ready_responses
    assert ready_responses["503"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ErrorResponse"
    )

    neutral_schema = json.loads(
        (
            Path(__file__).parents[4]
            / "packages"
            / "contracts"
            / "schemas"
            / "health.schema.json"
        ).read_text(encoding="utf-8"),
    )
    assert set(schema["components"]["schemas"]["HealthResponse"]["required"]) == set(
        neutral_schema["required"]
    )


def test_health_response_requires_service() -> None:
    with pytest.raises(ValidationError):
        HealthResponse(status="ok", version="0.1.0")


def test_health_response_requires_nonempty_version() -> None:
    with pytest.raises(ValidationError):
        HealthResponse(service="mosaic-api", status="ok", version="")


@pytest.mark.asyncio
async def test_enabled_chat_stack_requires_worker_and_relay_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.health as health_module

    async def ready() -> bool:
        return True

    async def relay_not_ready(*, event_type: str) -> bool:
        del event_type
        return False

    monkeypatch.setattr(
        health_module,
        "settings",
        type("SettingsStub", (), {"chat_submission_enabled": True})(),
    )
    monkeypatch.setattr(health_module, "is_chat_worker_ready", ready)
    monkeypatch.setattr(health_module, "is_outbox_relay_ready", relay_not_ready)

    assert await health_module.chat_stack_ready() is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_value", "video_value", "relay_value", "expected"),
    [
        (True, True, True, True),
        (False, True, True, False),
        (True, False, True, False),
        (True, True, False, False),
    ],
)
async def test_enabled_generation_stack_requires_both_workers_and_relay_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
    media_value: bool,
    video_value: bool,
    relay_value: bool,
    expected: bool,
) -> None:
    import app.api.health as health_module

    recorded_dependencies: list[tuple[str, bool]] = []

    async def media_ready() -> bool:
        return media_value

    async def video_ready() -> bool:
        return video_value

    async def relay_ready(*, event_type: str) -> bool:
        del event_type
        return relay_value

    def record_dependency(*, dependency: str, ready: bool) -> None:
        recorded_dependencies.append((dependency, ready))

    monkeypatch.setattr(
        health_module,
        "settings",
        type("SettingsStub", (), {"generation_submission_enabled": True})(),
    )
    monkeypatch.setattr(health_module, "is_generation_media_worker_ready", media_ready)
    monkeypatch.setattr(health_module, "is_generation_video_worker_ready", video_ready)
    monkeypatch.setattr(health_module, "is_outbox_relay_ready", relay_ready)
    monkeypatch.setattr(health_module, "record_dependency_ready", record_dependency)

    assert await health_module.generation_stack_ready() is expected
    assert ("generation_media_worker", media_value) in recorded_dependencies
    assert ("generation_video_worker", video_value) in recorded_dependencies
    assert ("generation_worker", media_value and video_value) in recorded_dependencies


@pytest.mark.asyncio
@pytest.mark.parametrize("pepper", [None, "s" * 31])
async def test_ready_fails_closed_for_non_development_session_token_codec(
    monkeypatch: pytest.MonkeyPatch,
    pepper: str | None,
) -> None:
    import app.api.health as health_module

    monkeypatch.setattr(
        health_module,
        "settings",
        SimpleNamespace(app_environment="staging", app_version="0.1.0"),
    )
    if pepper is None:
        monkeypatch.delenv("MOSAIC_SESSION_TOKEN_PEPPER", raising=False)
    else:
        monkeypatch.setenv("MOSAIC_SESSION_TOKEN_PEPPER", pepper)

    app = create_app()
    app.dependency_overrides[database_ready] = lambda: True
    app.dependency_overrides[redis_ready] = lambda: True
    app.dependency_overrides[provider_ready] = lambda: True
    app.dependency_overrides[generation_stack_ready] = lambda: True
    app.dependency_overrides[chat_stack_ready] = lambda: True

    async for client in client_for(app):
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_DEPENDENCY_NOT_READY"
    assert pepper is None or pepper not in response.text


@pytest.mark.asyncio
async def test_ready_accepts_constructible_non_development_session_token_codec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.health as health_module

    pepper = "p" * 32
    monkeypatch.setenv("MOSAIC_SESSION_TOKEN_PEPPER", pepper)
    monkeypatch.setattr(
        health_module,
        "settings",
        SimpleNamespace(app_environment="staging", app_version="0.1.0"),
    )

    app = create_app()
    app.dependency_overrides[database_ready] = lambda: True
    app.dependency_overrides[redis_ready] = lambda: True
    app.dependency_overrides[provider_ready] = lambda: True
    app.dependency_overrides[generation_stack_ready] = lambda: True
    app.dependency_overrides[chat_stack_ready] = lambda: True

    async for client in client_for(app):
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert pepper not in response.text
