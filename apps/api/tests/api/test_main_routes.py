import httpx
import pytest

from app.main import create_app


def test_main_app_registers_phase_three_auth_and_catalog_routes() -> None:
    paths = create_app().openapi()["paths"]

    assert {
        "/api/v1/auth/me",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/password/change",
        "/api/v1/auth/sessions",
        "/api/v1/auth/sessions/{session_id}",
        "/api/v1/auth/register",
        "/api/v1/models",
        "/api/v1/generations",
        "/api/v1/generations/{job_id}",
        "/api/v1/conversations",
        "/api/v1/conversations/{conversation_id}",
        "/api/v1/conversations/{conversation_id}/messages",
        "/api/v1/conversations/{conversation_id}/requests/{request_id}/resume",
        "/api/v1/conversations/{conversation_id}/messages/{message_id}/regenerate",
        "/api/v1/conversations/{conversation_id}/requests/{request_id}/stop",
        "/api/v1/usage",
    }.issubset(paths)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/me",
        "/api/v1/models",
        "/api/v1/conversations",
        "/api/v1/usage",
        "/api/v1/generations/00000000-0000-0000-0000-000000000001",
    ],
)
async def test_protected_phase_three_routes_fail_closed_without_session(path: str) -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
