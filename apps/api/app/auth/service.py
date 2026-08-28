"""Application service for native, cookie-backed multi-tenant auth."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.audit.writer import AuditContext
from app.auth.errors import AuthError
from app.auth.rate_limit import (
    LoginRateLimiter,
    LoginRateLimiterUnavailable,
    RedisLoginRateLimiter,
)
from app.auth.repository import (
    AuthRepositoryPort,
    CurrentAuth,
    CurrentPasswordInvalid,
    OneTimeCredentialUnavailable,
    RegistrationConflict,
    SessionNotFound,
    SessionRecord,
    TenantSelectionRequired,
    UserSessionRecord,
)
from app.contracts.auth import LoginRequest, RegisterRequest
from app.core.settings import Settings, settings
from app.security.passwords import PasswordHasher
from app.security.tokens import OpaqueTokenCodec

_EMPTY_AUDIT_CONTEXT = AuditContext()


class AuthService:
    """Coordinates password verification, admission, and short DB writes."""

    def __init__(
        self,
        repository: AuthRepositoryPort,
        *,
        password_hasher: PasswordHasher,
        token_codec: OpaqueTokenCodec,
        login_limiter: LoginRateLimiter,
        config: Settings | None = None,
    ) -> None:
        self._repository = repository
        self._password_hasher = password_hasher
        self._token_codec = token_codec
        self._login_limiter = login_limiter
        self._settings = config or settings

    async def register(
        self,
        payload: RegisterRequest,
        *,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: AuditContext = _EMPTY_AUDIT_CONTEXT,
    ) -> SessionRecord:
        if not self._settings.auth_registration_enabled:
            raise AuthError(
                status_code=404,
                code="AUTH_ROUTE_NOT_FOUND",
                message="请求不存在",
            )
        password_hash = await asyncio.to_thread(
            self._password_hasher.hash,
            payload.password,
        )
        try:
            return await self._repository.register(
                email=payload.email,
                password_hash=password_hash,
                tenant_name=payload.tenant_name,
                tenant_slug=payload.tenant_slug,
                hasher=self._password_hasher,
                codec=self._token_codec,
                session_ttl_seconds=self._settings.session_ttl_seconds,
                ip_address=ip_address,
                user_agent=user_agent,
                audit_context=audit_context,
            )
        except RegistrationConflict as exc:
            # The response intentionally does not reveal whether email or slug
            # was the conflicting unique value.
            raise AuthError(
                status_code=409,
                code="REGISTRATION_UNAVAILABLE",
                message="注册信息不可用",
            ) from exc

    async def login(
        self,
        payload: LoginRequest,
        *,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: AuditContext = _EMPTY_AUDIT_CONTEXT,
    ) -> SessionRecord:
        limiter_keys = RedisLoginRateLimiter.key_materials(payload.account, ip_address)
        try:
            admitted = True
            for limiter_key in limiter_keys:
                if not await self._login_limiter.allow(limiter_key):
                    admitted = False
                    break
        except LoginRateLimiterUnavailable as exc:
            raise AuthError(
                status_code=503,
                code="AUTHENTICATION_UNAVAILABLE",
                message="认证服务暂时不可用",
                retryable=True,
            ) from exc
        if not admitted:
            raise AuthError(
                status_code=429,
                code="AUTHENTICATION_RATE_LIMITED",
                message="请求过于频繁，请稍后再试",
                retryable=True,
            )

        try:
            login_record = await self._repository.authenticate(
                account=payload.account,
                password=payload.password,
                tenant_slug=payload.tenant_slug,
                hasher=self._password_hasher,
                now=datetime.now(UTC),
                max_failed_attempts=self._settings.auth_max_failed_login_attempts,
                lockout_seconds=self._settings.auth_lockout_seconds,
            )
        except TenantSelectionRequired as exc:
            raise AuthError(
                status_code=409,
                code="TENANT_SELECTION_REQUIRED",
                message="该账号属于多个工作区，请指定工作区",
                details={"tenantSlugRequired": True},
            ) from exc

        if login_record is None:
            raise AuthError(
                status_code=401,
                code="AUTHENTICATION_FAILED",
                message="账号或密码错误",
            )

        try:
            # Reset only the exact account+IP pair. Account and IP budgets
            # remain in force so successful logins cannot erase broader abuse.
            await self._login_limiter.reset(limiter_keys[-1])
        except LoginRateLimiterUnavailable as exc:
            # Do not issue a session if the shared admission state cannot be
            # updated authoritatively after a successful credential check.
            raise AuthError(
                status_code=503,
                code="AUTHENTICATION_UNAVAILABLE",
                message="认证服务暂时不可用",
                retryable=True,
            ) from exc

        try:
            session = await self._repository.create_session(
                user_id=login_record.user_id,
                tenant_id=login_record.tenant_id,
                codec=self._token_codec,
                session_ttl_seconds=self._settings.session_ttl_seconds,
                ip_address=ip_address,
                user_agent=user_agent,
                audit_context=audit_context,
                consume_one_time_credential=login_record.password_change_required,
            )
        except OneTimeCredentialUnavailable as exc:
            raise AuthError(
                status_code=401,
                code="AUTHENTICATION_FAILED",
                message="账号或密码错误",
            ) from exc
        return replace(
            session,
            password_change_required=login_record.password_change_required,
        )

    async def change_password(
        self,
        auth: CurrentAuth,
        *,
        current_password: str,
        new_password: str,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: AuditContext = _EMPTY_AUDIT_CONTEXT,
    ) -> SessionRecord:
        if not 12 <= len(new_password) <= 128:
            raise AuthError(
                status_code=422,
                code="PASSWORD_POLICY_INVALID",
                message="新密码长度必须为 12 到 128 个字符",
            )
        new_password_hash = await asyncio.to_thread(
            self._password_hasher.hash,
            new_password,
        )
        try:
            session = await self._repository.change_password(
                user_id=auth.user_id,
                tenant_id=auth.tenant_id,
                session_id=auth.session_id,
                current_password=current_password,
                new_password_hash=new_password_hash,
                hasher=self._password_hasher,
                codec=self._token_codec,
                session_ttl_seconds=self._settings.session_ttl_seconds,
                ip_address=ip_address,
                user_agent=user_agent,
                audit_context=audit_context,
            )
        except CurrentPasswordInvalid as exc:
            raise AuthError(
                status_code=401,
                code="PASSWORD_CURRENT_INVALID",
                message="当前密码不正确",
            ) from exc
        except SessionNotFound as exc:
            raise AuthError(
                status_code=401,
                code="AUTHENTICATION_REQUIRED",
                message="请先登录",
            ) from exc
        return replace(session, password_change_required=False)

    async def current_auth(self, session_token: str | None) -> CurrentAuth | None:
        if not session_token:
            return None
        digest = self._token_codec.digest(session_token, purpose="session")
        return await self._repository.current_auth(
            session_token_digest=digest,
            now=datetime.now(UTC),
            idle_ttl_seconds=self._settings.session_idle_ttl_seconds,
            touch_interval_seconds=self._settings.session_touch_interval_seconds,
        )

    async def logout(
        self,
        session_token: str | None,
        *,
        audit_context: AuditContext = _EMPTY_AUDIT_CONTEXT,
    ) -> None:
        if not session_token:
            return
        digest = self._token_codec.digest(session_token, purpose="session")
        await self._repository.revoke_session(
            session_token_digest=digest,
            now=datetime.now(UTC),
            audit_context=audit_context,
        )

    async def list_sessions(self, auth: CurrentAuth) -> tuple[UserSessionRecord, ...]:
        return await self._repository.list_user_sessions(
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            now=datetime.now(UTC),
            idle_ttl_seconds=self._settings.session_idle_ttl_seconds,
        )

    async def revoke_other_session(
        self,
        auth: CurrentAuth,
        session_id: UUID,
        *,
        audit_context: AuditContext = _EMPTY_AUDIT_CONTEXT,
    ) -> None:
        if session_id == auth.session_id:
            raise AuthError(
                status_code=409,
                code="CURRENT_SESSION_REQUIRES_LOGOUT",
                message="当前会话请使用退出登录",
            )
        revoked = await self._repository.revoke_user_session(
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            session_id=session_id,
            now=datetime.now(UTC),
            audit_context=audit_context,
        )
        if not revoked:
            raise AuthError(
                status_code=404,
                code="SESSION_NOT_FOUND",
                message="会话不存在",
            )

    def verify_csrf(
        self,
        auth: CurrentAuth,
        csrf_token: str | None,
        csrf_cookie: str | None,
    ) -> None:
        # The readable cookie and header must agree before the DB-bound hash
        # check.  compare_digest is constant-time for equal-length values.
        if (
            not csrf_token
            or not csrf_cookie
            or not secrets.compare_digest(csrf_cookie, csrf_token)
            or not self._token_codec.matches(
                csrf_token,
                auth.csrf_token_hash,
                purpose="csrf",
            )
        ):
            raise AuthError(
                status_code=403,
                code="CSRF_TOKEN_INVALID",
                message="请求校验失败，请刷新后重试",
            )

    @property
    def token_codec(self) -> OpaqueTokenCodec:
        return self._token_codec


class AuthServiceFactory(Protocol):
    def __call__(self) -> AuthService: ...


__all__ = ["AuthService", "AuthServiceFactory"]
