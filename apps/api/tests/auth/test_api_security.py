from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import current_auth, validate_same_site_request
from app.auth.errors import AuthError
from app.auth.rate_limit import (
    LoginRateLimiterUnavailable,
    RedisLoginRateLimiter,
)
from app.auth.repository import CurrentAuth, SessionRecord, UserSessionRecord
from app.contracts.auth import LoginRequest


def _request(headers: Mapping[str, str]) -> Request:
    encoded = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/auth/login",
            "raw_path": b"/api/v1/auth/login",
            "query_string": b"",
            "headers": encoded,
            "client": ("127.0.0.1", 50000),
            "server": ("api.internal", 80),
        }
    )


def test_same_site_check_uses_explicit_full_origins() -> None:
    validate_same_site_request(
        _request(
            {
                "host": "api.internal",
                "origin": "http://localhost:3000",
                "content-type": "application/json",
            }
        ),
        require_json=True,
    )

    with pytest.raises(AuthError) as error:
        validate_same_site_request(
            _request(
                {
                    "host": "api.internal",
                    "origin": "https://evil.example",
                    "content-type": "application/json",
                }
            ),
            require_json=True,
        )
    assert error.value.code == "AUTH_ORIGIN_INVALID"


def test_same_site_check_rejects_non_json_public_auth_requests() -> None:
    with pytest.raises(AuthError) as error:
        validate_same_site_request(
            _request({"host": "api.internal", "origin": "http://localhost:3000"}),
            require_json=True,
        )
    assert error.value.status_code == 415


class _FailingRedis:
    async def eval(self, *_: object) -> object:
        raise OSError("redis unavailable")

    async def delete(self, *_: object) -> int:
        raise OSError("redis unavailable")


@pytest.mark.asyncio
async def test_redis_login_limiter_fails_closed_on_transport_error() -> None:
    limiter = RedisLoginRateLimiter(
        _FailingRedis(),
        environment="test",
        limit=20,
        window_seconds=60,
    )

    with pytest.raises(LoginRateLimiterUnavailable):
        await limiter.allow(RedisLoginRateLimiter.key_material("owner@example.com", "127.0.0.1"))


def test_login_limiter_has_independent_account_ip_and_pair_budgets() -> None:
    materials = RedisLoginRateLimiter.key_materials(
        "owner@example.com",
        "127.0.0.1",
    )

    assert len(materials) == 3
    assert len(set(materials)) == 3
    assert all(len(item) == 64 for item in materials)
    assert all("owner@example.com" not in item for item in materials)


class _RegistrationDisabledService:
    async def register(self, *args: object, **kwargs: object) -> None:
        raise AuthError(status_code=404, code="AUTH_ROUTE_NOT_FOUND", message="请求不存在")


@pytest.mark.asyncio
async def test_register_disabled_is_a_generic_not_found_error() -> None:
    from app.main import create_app

    app = create_app()
    service = _RegistrationDisabledService()
    from app.auth.dependencies import get_auth_service

    app.dependency_overrides[get_auth_service] = lambda: service  # type: ignore[assignment]
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://localhost:3000",
        ) as client:
            response = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "owner@example.com",
                    "password": "correct-password",
                    "tenant_name": "Acme",
                    "tenant_slug": "acme",
                },
                headers={"origin": "http://localhost:3000"},
            )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "AUTH_ROUTE_NOT_FOUND"
        assert len(response.headers.get_list("x-request-id")) == 1
    finally:
        app.dependency_overrides.clear()


class _SuccessfulLoginService:
    async def login(
        self,
        payload: LoginRequest,
        *,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: object,
    ) -> SessionRecord:
        assert payload.account == "owner@example.com"
        assert ip_address
        assert user_agent
        return SessionRecord(
            session_id=uuid4(),
            user_id=uuid4(),
            tenant_id=uuid4(),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            session_token="session-token-value",
            csrf_token="abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
        )


@pytest.mark.asyncio
async def test_login_returns_exact_session_and_secure_cookie_attributes() -> None:
    from app.auth.dependencies import get_auth_service
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: _SuccessfulLoginService()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://localhost:3000",
        ) as client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"account": "owner@example.com", "password": "correct-password"},
                headers={"origin": "http://localhost:3000"},
            )

        assert response.status_code == 200
        assert response.json() == {
            "authenticated": True,
            "passwordChangeRequired": False,
        }
        cookies = response.headers.get_list("set-cookie")
        session_cookie = next(value for value in cookies if value.startswith("mosaic_session="))
        csrf_cookie = next(value for value in cookies if value.startswith("mosaic_csrf="))
        assert "HttpOnly" in session_cookie
        assert "Secure" in session_cookie
        assert "SameSite=lax" in session_cookie
        assert "Path=/" in session_cookie
        assert "HttpOnly" not in csrf_cookie
        assert "Secure" in csrf_cookie
        assert response.headers["cache-control"] == "no-store"
    finally:
        app.dependency_overrides.clear()


class _SessionManagementService:
    def __init__(self, record: UserSessionRecord) -> None:
        self.record = record
        self.revoked: UUID | None = None

    async def list_sessions(self, _auth: CurrentAuth) -> tuple[UserSessionRecord, ...]:
        return (self.record,)

    async def revoke_other_session(
        self,
        _auth: CurrentAuth,
        session_id: UUID,
        *,
        audit_context: object,
    ) -> None:
        assert audit_context is not None
        self.revoked = session_id


class _PasswordChangeService:
    def __init__(self, session: SessionRecord) -> None:
        self.session = session
        self.changed: dict[str, object] | None = None

    def verify_csrf(self, *_: object) -> None:
        return None

    async def change_password(self, auth: CurrentAuth, **kwargs: object) -> SessionRecord:
        self.changed = {"auth": auth, **kwargs}
        return self.session


@pytest.mark.asyncio
async def test_session_management_contract_is_exact_and_csrf_scoped() -> None:
    from app.auth.dependencies import current_auth, get_auth_service, require_authenticated_csrf
    from app.main import create_app

    session_id = uuid4()
    now = datetime.now(UTC)
    auth = CurrentAuth(
        session_id=session_id,
        user_id=uuid4(),
        tenant_id=uuid4(),
        tenant_slug="acme",
        user_email="owner@example.com",
        membership_id=uuid4(),
        role="owner",
        password_change_required=False,
        csrf_token_hash="c" * 64,
        session_token_digest="d" * 64,
    )
    service = _SessionManagementService(
        UserSessionRecord(
            session_id=session_id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
            ip_address="127.0.0.1",
            user_agent="test-agent",
        )
    )
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[current_auth] = lambda: auth
    app.dependency_overrides[require_authenticated_csrf] = lambda: auth
    target = uuid4()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://localhost:3000",
        ) as client:
            listed = await client.get("/api/v1/auth/sessions")
            revoked = await client.delete(f"/api/v1/auth/sessions/{target}")

        assert listed.status_code == 200
        assert listed.json() == {
            "items": [
                {
                    "sessionId": str(session_id),
                    "current": True,
                    "createdAt": now.isoformat().replace("+00:00", "Z"),
                    "lastSeenAt": now.isoformat().replace("+00:00", "Z"),
                    "expiresAt": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    "ipAddress": "127.0.0.1",
                    "userAgent": "test-agent",
                }
            ]
        }
        assert revoked.status_code == 204
        assert service.revoked == target
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_restricted_session_can_change_password_and_receives_rotated_cookies() -> None:
    from app.auth.dependencies import get_auth_service, require_authenticated_csrf_allow_restricted
    from app.main import create_app

    now = datetime.now(UTC)
    auth = CurrentAuth(
        session_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        tenant_slug="acme",
        user_email="owner@example.com",
        membership_id=uuid4(),
        role="owner",
        password_change_required=True,
        csrf_token_hash="c" * 64,
        session_token_digest="d" * 64,
    )
    service = _PasswordChangeService(
        SessionRecord(
            session_id=uuid4(),
            user_id=auth.user_id,
            tenant_id=auth.tenant_id,
            expires_at=now + timedelta(hours=1),
            session_token="rotated-session-token",
            csrf_token="rotated-csrf-token-abcdefghijklmnopqrstuvwxyz",
        )
    )
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[require_authenticated_csrf_allow_restricted] = lambda: auth
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://localhost:3000",
        ) as client:
            response = await client.post(
                "/api/v1/auth/password/change",
                json={
                    "current_password": "temporary-credential",
                    "new_password": "a-valid-password-12",
                },
                headers={"origin": "http://localhost:3000"},
            )

        assert response.status_code == 204
        assert service.changed is not None
        assert service.changed["auth"] is auth
        assert service.changed["new_password"] == "a-valid-password-12"
        cookies = response.headers.get_list("set-cookie")
        assert any(value.startswith("mosaic_session=rotated-session-token") for value in cookies)
        assert any(value.startswith("mosaic_csrf=rotated-csrf-token") for value in cookies)
        assert response.headers["cache-control"] == "no-store"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_normal_auth_dependency_blocks_restricted_sessions() -> None:
    auth = CurrentAuth(
        session_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        tenant_slug="acme",
        user_email="owner@example.com",
        membership_id=uuid4(),
        role="owner",
        password_change_required=True,
        csrf_token_hash="c" * 64,
        session_token_digest="d" * 64,
    )

    with pytest.raises(AuthError) as error:
        await current_auth(auth)

    assert error.value.code == "PASSWORD_CHANGE_REQUIRED"
