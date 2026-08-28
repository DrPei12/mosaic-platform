from uuid import UUID

import httpx
import pytest
from fastapi import APIRouter

from app.main import create_app


def assert_uuid4(value: str) -> None:
    parsed = UUID(value)
    assert parsed.version == 4
    assert str(parsed) == value


@pytest.mark.asyncio
async def test_request_id_is_server_owned_and_returned() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/health/live",
            headers={"x-request-id": "attacker-controlled\r\nforged: value"},
        )

    assert response.status_code == 200
    assert_uuid4(response.headers["x-request-id"])
    assert response.headers["x-request-id"] != "attacker-controlled"


@pytest.mark.asyncio
async def test_readiness_error_uses_the_same_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unavailable() -> bool:
        return False

    monkeypatch.setattr("app.api.health.database_ready", unavailable)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    request_id = response.headers["x-request-id"]
    assert_uuid4(request_id)
    assert response.json()["error"]["request_id"] == request_id


@pytest.mark.asyncio
async def test_unhandled_error_is_sanitized() -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/test-error")
    async def test_error() -> None:
        raise RuntimeError("Authorization: Bearer secret-provider-value")

    app.include_router(router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-error")

    assert response.status_code == 500
    request_id = response.headers["x-request-id"]
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "服务暂时不可用",
            "request_id": request_id,
            "retryable": True,
            "details": None,
        }
    }
    assert "secret-provider-value" not in response.text
