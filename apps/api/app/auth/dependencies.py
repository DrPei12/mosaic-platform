"""FastAPI dependencies for auth context, cookies, and CSRF."""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Annotated, cast
from urllib.parse import urlsplit

from fastapi import Depends, Request
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthError
from app.auth.rate_limit import RedisLoginRateLimiter, RedisRateLimitClient
from app.auth.repository import CurrentAuth, SQLAuthRepository
from app.auth.service import AuthService
from app.core.settings import settings
from app.infrastructure.database import get_db_session
from app.infrastructure.redis import redis_client
from app.infrastructure.tenant_context import bind_session_tenant
from app.security.passwords import PasswordHasher
from app.security.tokens import OpaqueTokenCodec, SessionTokenConfigurationError

CSRF_COOKIE_NAME = "mosaic_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"


@lru_cache(maxsize=1)
def get_password_hasher() -> PasswordHasher:
    return PasswordHasher()


_development_codec: OpaqueTokenCodec | None = None


def get_token_codec() -> OpaqueTokenCodec:
    global _development_codec
    try:
        return OpaqueTokenCodec.from_process_environment()
    except SessionTokenConfigurationError as exc:
        if settings.app_environment != "development":
            raise AuthError(
                status_code=503,
                code="AUTHENTICATION_UNAVAILABLE",
                message="认证服务暂时不可用",
                retryable=True,
            ) from exc
        # Local HTTP development may omit a persistent pepper deliberately.
        # This process-scoped fallback is not permitted in production and
        # invalidates sessions on restart; no secret is written to the repo.
        if _development_codec is None:
            _development_codec = OpaqueTokenCodec(
                SecretStr(secrets.token_urlsafe(48)),
            )
        return _development_codec


@lru_cache(maxsize=1)
def get_login_limiter() -> RedisLoginRateLimiter:
    return RedisLoginRateLimiter(
        cast(RedisRateLimitClient, redis_client),
        environment=settings.app_environment,
        limit=settings.auth_login_rate_limit,
        window_seconds=settings.auth_login_rate_window_seconds,
    )


async def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    password_hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    token_codec: Annotated[OpaqueTokenCodec, Depends(get_token_codec)],
    login_limiter: Annotated[RedisLoginRateLimiter, Depends(get_login_limiter)],
) -> AuthService:
    return AuthService(
        SQLAuthRepository(session),
        password_hasher=password_hasher,
        token_codec=token_codec,
        login_limiter=login_limiter,
    )


async def current_auth_optional(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CurrentAuth | None:
    auth = await service.current_auth(request.cookies.get(settings.session_cookie_name))
    if auth is not None:
        bind_session_tenant(session, auth.tenant_id)
    return auth


async def current_auth(
    auth: Annotated[CurrentAuth | None, Depends(current_auth_optional)],
) -> CurrentAuth:
    if auth is None:
        raise AuthError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message="请先登录",
        )
    if auth.password_change_required:
        raise AuthError(
            status_code=403,
            code="PASSWORD_CHANGE_REQUIRED",
            message="请先修改密码",
        )
    return auth


async def current_auth_allow_restricted(
    auth: Annotated[CurrentAuth | None, Depends(current_auth_optional)],
) -> CurrentAuth:
    if auth is None:
        raise AuthError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message="请先登录",
        )
    return auth


def validate_same_site_request(request: Request, *, require_json: bool) -> None:
    """Reject cross-site auth writes and non-JSON login/register requests."""

    if require_json:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise AuthError(
                status_code=415,
                code="AUTH_REQUEST_INVALID",
                message="请求格式不受支持",
            )

    host = request.headers.get("host")
    origin = request.headers.get("origin")
    if not host:
        raise AuthError(
            status_code=400,
            code="AUTH_REQUEST_INVALID",
            message="请求校验失败",
        )
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AuthError(
                status_code=403,
                code="AUTH_ORIGIN_INVALID",
                message="请求校验失败",
            )
        full_origin = f"{parsed.scheme}://{parsed.netloc}".lower().rstrip("/")
        allowed_origins = {
            value.lower().rstrip("/") for value in settings.auth_allowed_origins
        }
        if full_origin not in allowed_origins:
            raise AuthError(
                status_code=403,
                code="AUTH_ORIGIN_INVALID",
                message="请求校验失败",
            )
    elif request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise AuthError(
            status_code=403,
            code="AUTH_ORIGIN_INVALID",
            message="请求校验失败",
        )


async def require_public_auth_request(request: Request) -> None:
    validate_same_site_request(request, require_json=True)


async def require_authenticated_csrf(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    auth: Annotated[CurrentAuth, Depends(current_auth)],
) -> CurrentAuth:
    validate_same_site_request(request, require_json=False)
    service.verify_csrf(
        auth,
        request.headers.get(CSRF_HEADER_NAME),
        request.cookies.get(CSRF_COOKIE_NAME),
    )
    return auth


async def require_authenticated_csrf_allow_restricted(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    auth: Annotated[CurrentAuth, Depends(current_auth_allow_restricted)],
) -> CurrentAuth:
    validate_same_site_request(request, require_json=False)
    service.verify_csrf(
        auth,
        request.headers.get(CSRF_HEADER_NAME),
        request.cookies.get(CSRF_COOKIE_NAME),
    )
    return auth


__all__ = [
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "current_auth",
    "current_auth_allow_restricted",
    "current_auth_optional",
    "get_auth_service",
    "require_authenticated_csrf",
    "require_authenticated_csrf_allow_restricted",
    "require_public_auth_request",
    "validate_same_site_request",
]
