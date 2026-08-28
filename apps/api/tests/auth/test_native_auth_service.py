from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from app.auth.errors import AuthError
from app.auth.repository import (
    CurrentAuth,
    CurrentPasswordInvalid,
    LoginRecord,
    SessionRecord,
    UserSessionRecord,
)
from app.auth.service import AuthService
from app.contracts.auth import LoginRequest
from app.core.settings import Settings
from app.security.passwords import PasswordHasher, PasswordHashParameters
from app.security.tokens import OpaqueTokenCodec


class FakeLimiter:
    def __init__(self) -> None:
        self.allowed = True
        self.allow_count = 0
        self.reset_count = 0

    async def allow(self, _: str) -> bool:
        self.allow_count += 1
        return self.allowed

    async def reset(self, _: str) -> None:
        self.reset_count += 1


class FakeRepository:
    def __init__(self, login_record: LoginRecord | None) -> None:
        self.login_record = login_record
        self.created: dict[str, Any] | None = None
        self.created_session: dict[str, Any] | None = None
        self.changed_password: dict[str, Any] | None = None
        self.password_change_error: Exception | None = None
        self.current_auth_kwargs: dict[str, Any] | None = None
        self.revoked_user_session: dict[str, Any] | None = None
        self.user_sessions: tuple[UserSessionRecord, ...] = ()

    async def register(self, **kwargs: Any) -> SessionRecord:
        self.created = kwargs
        return _session(kwargs["user_id"] if "user_id" in kwargs else uuid4())

    async def authenticate(self, **_: Any) -> LoginRecord | None:
        return self.login_record

    async def create_session(self, **kwargs: Any) -> SessionRecord:
        self.created_session = kwargs
        return _session(kwargs["user_id"], kwargs["tenant_id"])

    async def change_password(self, **kwargs: Any) -> SessionRecord:
        self.changed_password = kwargs
        if self.password_change_error is not None:
            raise self.password_change_error
        return _session(kwargs["user_id"], kwargs["tenant_id"])

    async def current_auth(self, **kwargs: Any) -> CurrentAuth | None:
        self.current_auth_kwargs = kwargs
        return None

    async def revoke_session(self, **_: Any) -> None:
        return None

    async def list_user_sessions(self, **_: Any) -> tuple[UserSessionRecord, ...]:
        return self.user_sessions

    async def revoke_user_session(self, **kwargs: Any) -> bool:
        self.revoked_user_session = kwargs
        return True


def _session(user_id: UUID, tenant_id: UUID | None = None) -> SessionRecord:
    return SessionRecord(
        session_id=uuid4(),
        user_id=user_id,
        tenant_id=tenant_id or uuid4(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        session_token="session-token",
        csrf_token="csrf-token",
    )


def _service(repository: FakeRepository, limiter: FakeLimiter) -> AuthService:
    return AuthService(
        repository,
        password_hasher=PasswordHasher(
            PasswordHashParameters(
                time_cost=1,
                memory_cost_kib=16_384,
                parallelism=1,
                hash_len=16,
                salt_len=16,
            )
        ),
        token_codec=OpaqueTokenCodec(SecretStr("p" * 32)),
        login_limiter=limiter,
        config=Settings(_env_file=None, auth_registration_enabled=True, session_cookie_secure=False),
    )


@pytest.mark.asyncio
async def test_login_resets_limiter_only_after_valid_authentication() -> None:
    user_id = uuid4()
    limiter = FakeLimiter()
    service = _service(FakeRepository(LoginRecord(user_id=user_id, tenant_id=uuid4())), limiter)

    session = await service.login(
        LoginRequest(account="owner@example.com", password="correct-password"),
        ip_address="127.0.0.1",
        user_agent="test",
    )

    assert session.user_id == user_id
    assert limiter.allow_count == 3
    assert limiter.reset_count == 1


@pytest.mark.asyncio
async def test_login_marks_one_time_credential_sessions_as_restricted() -> None:
    repository = FakeRepository(
        LoginRecord(user_id=uuid4(), tenant_id=uuid4(), password_change_required=True)
    )
    session = await _service(repository, FakeLimiter()).login(
        LoginRequest(account="owner@example.com", password="correct-password"),
        ip_address="127.0.0.1",
        user_agent="test",
    )

    assert session.password_change_required is True
    assert repository.created_session is not None
    assert repository.created_session["consume_one_time_credential"] is True


@pytest.mark.asyncio
async def test_password_change_hashes_new_password_and_rotates_session() -> None:
    repository = FakeRepository(None)
    service = _service(repository, FakeLimiter())
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

    session = await service.change_password(
        auth,
        current_password="temporary-credential",
        new_password="a-valid-password-12",
        ip_address="127.0.0.1",
        user_agent="test",
    )

    assert session.password_change_required is False
    assert repository.changed_password is not None
    assert repository.changed_password["user_id"] == auth.user_id
    assert repository.changed_password["session_id"] == auth.session_id
    assert repository.changed_password["new_password_hash"] != "a-valid-password-12"


@pytest.mark.asyncio
async def test_password_change_rejects_wrong_current_password() -> None:
    repository = FakeRepository(None)
    repository.password_change_error = CurrentPasswordInvalid()
    service = _service(repository, FakeLimiter())
    auth = CurrentAuth(
        session_id=uuid4(),
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

    with pytest.raises(AuthError) as error:
        await service.change_password(
            auth,
            current_password="wrong-password",
            new_password="a-valid-password-12",
            ip_address=None,
            user_agent=None,
        )

    assert error.value.code == "PASSWORD_CURRENT_INVALID"


@pytest.mark.asyncio
async def test_csrf_requires_cookie_header_equality_and_database_match() -> None:
    limiter = FakeLimiter()
    service = _service(FakeRepository(None), limiter)
    csrf = service.token_codec.issue("csrf")
    auth = CurrentAuth(
        session_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        tenant_slug="acme",
        user_email="owner@example.com",
        membership_id=uuid4(),
        role="owner",
        password_change_required=False,
        csrf_token_hash=csrf.digest,
        session_token_digest="d" * 64,
    )

    with pytest.raises(AuthError):
        service.verify_csrf(auth, csrf.plaintext.get_secret_value(), "different")

    service.verify_csrf(
        auth,
        csrf.plaintext.get_secret_value(),
        csrf.plaintext.get_secret_value(),
    )


@pytest.mark.asyncio
async def test_current_auth_applies_idle_and_touch_policy() -> None:
    repository = FakeRepository(None)
    service = _service(repository, FakeLimiter())

    assert await service.current_auth("opaque-session") is None

    assert repository.current_auth_kwargs is not None
    assert repository.current_auth_kwargs["idle_ttl_seconds"] == 1_800
    assert repository.current_auth_kwargs["touch_interval_seconds"] == 300
    assert len(repository.current_auth_kwargs["session_token_digest"]) == 64


@pytest.mark.asyncio
async def test_revoke_other_session_is_scoped_to_current_user_and_tenant() -> None:
    repository = FakeRepository(None)
    service = _service(repository, FakeLimiter())
    auth = CurrentAuth(
        session_id=uuid4(),
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
    target = uuid4()

    await service.revoke_other_session(auth, target)

    assert repository.revoked_user_session is not None
    assert repository.revoked_user_session["tenant_id"] == auth.tenant_id
    assert repository.revoked_user_session["user_id"] == auth.user_id
    assert repository.revoked_user_session["session_id"] == target


@pytest.mark.asyncio
async def test_revoke_current_session_requires_logout() -> None:
    repository = FakeRepository(None)
    service = _service(repository, FakeLimiter())
    session_id = uuid4()
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

    with pytest.raises(AuthError) as error:
        await service.revoke_other_session(auth, session_id)

    assert error.value.code == "CURRENT_SESSION_REQUIRES_LOGOUT"
    assert repository.revoked_user_session is None
