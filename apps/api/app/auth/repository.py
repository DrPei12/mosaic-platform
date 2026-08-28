"""PostgreSQL-backed authentication repository.

Every public method owns a short transaction.  No repository method leaves a
transaction open while an external provider, Redis, or browser is involved.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import AuditContext, append_audit_event
from app.infrastructure.models import (
    AuthSessions,
    Memberships,
    ProductModels,
    TenantModelEntitlements,
    Tenants,
    Users,
    WalletAccounts,
)
from app.infrastructure.tenant_context import (
    bind_active_transaction_tenant,
    bind_session_tenant,
)
from app.security.passwords import PasswordHasher
from app.security.tokens import IssuedOpaqueToken, OpaqueTokenCodec


class RegistrationConflict(RuntimeError):
    """A registration collided with an existing globally unique identity."""


class TenantSelectionRequired(RuntimeError):
    """The password was valid but the user has multiple active tenants."""


class OneTimeCredentialUnavailable(RuntimeError):
    """The one-time credential was consumed, expired, or lost a race."""


class CurrentPasswordInvalid(RuntimeError):
    """The supplied current password does not match the account."""


class SessionNotFound(RuntimeError):
    """The session used for a password change is no longer active."""


@dataclass(frozen=True, slots=True)
class LoginRecord:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    password_change_required: bool = False


@dataclass(frozen=True, slots=True, repr=False)
class SessionRecord:
    session_id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    expires_at: datetime
    session_token: str
    csrf_token: str
    password_change_required: bool = False

    def __repr__(self) -> str:
        return (
            "SessionRecord("
            f"session_id={self.session_id!r}, user_id={self.user_id!r}, "
            f"tenant_id={self.tenant_id!r}, expires_at={self.expires_at!r}, "
            "session_token=<redacted>, csrf_token=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class CurrentAuth:
    session_id: uuid.UUID
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_slug: str
    user_email: str
    membership_id: uuid.UUID
    role: str
    password_change_required: bool
    csrf_token_hash: str
    session_token_digest: str

    def __repr__(self) -> str:
        return (
            "CurrentAuth("
            f"session_id={self.session_id!r}, user_id={self.user_id!r}, "
            f"tenant_id={self.tenant_id!r}, tenant_slug={self.tenant_slug!r}, "
            f"membership_id={self.membership_id!r}, role={self.role!r}, "
            "csrf_token_hash=<redacted>, session_token_digest=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class UserSessionRecord:
    session_id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None


class AuthRepositoryPort(Protocol):
    async def register(
        self,
        *,
        email: str,
        password_hash: str,
        tenant_name: str,
        tenant_slug: str,
        hasher: PasswordHasher,
        codec: OpaqueTokenCodec,
        session_ttl_seconds: int,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: AuditContext,
    ) -> SessionRecord: ...

    async def authenticate(
        self,
        *,
        account: str,
        password: str,
        tenant_slug: str | None,
        hasher: PasswordHasher,
        now: datetime,
        max_failed_attempts: int,
        lockout_seconds: int,
    ) -> LoginRecord | None: ...

    async def create_session(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        codec: OpaqueTokenCodec,
        session_ttl_seconds: int,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: AuditContext,
        consume_one_time_credential: bool = False,
    ) -> SessionRecord: ...

    async def change_password(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID,
        current_password: str,
        new_password_hash: str,
        hasher: PasswordHasher,
        codec: OpaqueTokenCodec,
        session_ttl_seconds: int,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: AuditContext,
    ) -> SessionRecord: ...

    async def current_auth(
        self,
        *,
        session_token_digest: str,
        now: datetime,
        idle_ttl_seconds: int,
        touch_interval_seconds: int,
    ) -> CurrentAuth | None: ...

    async def revoke_session(
        self,
        *,
        session_token_digest: str,
        now: datetime,
        audit_context: AuditContext,
    ) -> None: ...

    async def list_user_sessions(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        now: datetime,
        idle_ttl_seconds: int,
    ) -> tuple[UserSessionRecord, ...]: ...

    async def revoke_user_session(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        now: datetime,
        audit_context: AuditContext,
    ) -> bool: ...


class SQLAuthRepository:
    """Concrete repository using PostgreSQL through an injected AsyncSession."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self,
        *,
        email: str,
        password_hash: str,
        tenant_name: str,
        tenant_slug: str,
        hasher: PasswordHasher,
        codec: OpaqueTokenCodec,
        session_ttl_seconds: int,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: AuditContext,
    ) -> SessionRecord:
        del hasher  # the service owns hashing; kept in the port for fake parity
        try:
            async with self._session.begin():
                user = Users(
                    email=email,
                    password_hash=password_hash,
                    display_name=email.split("@", 1)[0][:160],
                    status="active",
                    failed_login_count=0,
                )
                tenant = Tenants(
                    slug=tenant_slug,
                    name=tenant_name,
                    status="active",
                    settings={},
                )
                self._session.add_all([user, tenant])
                await self._session.flush()
                await bind_active_transaction_tenant(self._session, tenant.id)

                membership = Memberships(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    role="owner",
                    status="active",
                )
                wallet = WalletAccounts(
                    tenant_id=tenant.id,
                    currency="PTS",
                    balance_minor=0,
                    reserved_minor=0,
                    version=0,
                    status="active",
                )
                self._session.add_all([membership, wallet])

                active_models = (
                    await self._session.execute(
                        select(ProductModels.id).where(ProductModels.status == "active")
                    )
                ).scalars()
                self._session.add_all(
                    [
                        TenantModelEntitlements(
                            tenant_id=tenant.id,
                            product_model_id=model_id,
                            enabled=True,
                            config={},
                        )
                        for model_id in active_models
                    ]
                )
                await self._session.flush()

                return await self._create_session_in_transaction(
                    user_id=user.id,
                    tenant_id=tenant.id,
                    codec=codec,
                    session_ttl_seconds=session_ttl_seconds,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    audit_context=audit_context,
                )
        except IntegrityError as exc:
            if _integrity_sqlstate(exc) != "23505":
                raise
            raise RegistrationConflict from exc

    async def authenticate(
        self,
        *,
        account: str,
        password: str,
        tenant_slug: str | None,
        hasher: PasswordHasher,
        now: datetime,
        max_failed_attempts: int,
        lockout_seconds: int,
    ) -> LoginRecord | None:
        selection_required = False
        login_record: LoginRecord | None = None
        async with self._session.begin():
            user = (
                await self._session.execute(
                    select(Users).where(Users.email == account).with_for_update()
                )
            ).scalar_one_or_none()
            if user is None:
                await asyncio.to_thread(hasher.verify_or_dummy, None, password)
                return None

            password_ok = await asyncio.to_thread(
                hasher.verify_or_dummy,
                user.password_hash,
                password,
            )
            if user.status != "active":
                return None

            if user.locked_until is not None and _as_utc(user.locked_until) <= now:
                user.locked_until = None
                user.failed_login_count = 0

            if user.locked_until is not None and _as_utc(user.locked_until) > now:
                return None

            if not password_ok:
                failed_attempts = int(user.failed_login_count) + 1
                user.failed_login_count = failed_attempts
                if failed_attempts >= max_failed_attempts:
                    user.locked_until = now + timedelta(seconds=lockout_seconds)
                return None

            memberships = (
                await self._session.execute(
                    select(Memberships, Tenants)
                    .join(Tenants, Memberships.tenant_id == Tenants.id)
                    .where(
                        Memberships.user_id == user.id,
                        Memberships.status == "active",
                        Tenants.status == "active",
                        *([Tenants.slug == tenant_slug] if tenant_slug else []),
                    )
                )
            ).all()
            if not memberships:
                return None
            if tenant_slug is None and len(memberships) > 1:
                selection_required = True
            else:
                _, tenant = memberships[0]
                await bind_active_transaction_tenant(self._session, tenant.id)
                password_change_required = bool(user.password_change_required)
                if password_change_required and (
                    user.credential_expires_at is None
                    or _as_utc(user.credential_expires_at) <= now
                    or user.credential_used_at is not None
                ):
                    return None
                if hasher.needs_rehash(user.password_hash):
                    user.password_hash = await asyncio.to_thread(hasher.hash, password)
                user.failed_login_count = 0
                user.locked_until = None
                login_record = LoginRecord(
                    user_id=user.id,
                    tenant_id=tenant.id,
                    password_change_required=password_change_required,
                )

        if selection_required:
            raise TenantSelectionRequired
        return login_record

    async def create_session(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        codec: OpaqueTokenCodec,
        session_ttl_seconds: int,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: AuditContext,
        consume_one_time_credential: bool = False,
    ) -> SessionRecord:
        bind_session_tenant(self._session, tenant_id)
        async with self._session.begin():
            return await self._create_session_in_transaction(
                user_id=user_id,
                tenant_id=tenant_id,
                codec=codec,
                session_ttl_seconds=session_ttl_seconds,
                ip_address=ip_address,
                user_agent=user_agent,
                audit_context=audit_context,
                consume_one_time_credential=consume_one_time_credential,
            )

    async def change_password(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID,
        current_password: str,
        new_password_hash: str,
        hasher: PasswordHasher,
        codec: OpaqueTokenCodec,
        session_ttl_seconds: int,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: AuditContext,
    ) -> SessionRecord:
        bind_session_tenant(self._session, tenant_id)
        async with self._session.begin():
            user = (
                await self._session.execute(
                    select(Users)
                    .where(Users.id == user_id, Users.status == "active")
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if user is None:
                raise SessionNotFound

            current_session = (
                await self._session.execute(
                    select(AuthSessions)
                    .where(
                        AuthSessions.id == session_id,
                        AuthSessions.user_id == user_id,
                        AuthSessions.tenant_id == tenant_id,
                        AuthSessions.status == "active",
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if current_session is None:
                raise SessionNotFound

            password_ok = await asyncio.to_thread(
                hasher.verify_or_dummy,
                user.password_hash,
                current_password,
            )
            if not password_ok:
                raise CurrentPasswordInvalid

            now = datetime.now(UTC)
            user.password_hash = new_password_hash
            user.password_changed_at = now
            user.password_change_required = False
            user.credential_expires_at = None
            user.credential_used_at = None
            user.failed_login_count = 0
            user.locked_until = None

            active_sessions = tuple(
                (
                    await self._session.execute(
                        select(AuthSessions)
                        .where(
                            AuthSessions.user_id == user_id,
                            AuthSessions.status == "active",
                        )
                        .with_for_update()
                    )
                ).scalars()
            )
            revoked_current_tenant = 0
            revoked_other_tenants = 0
            for session in active_sessions:
                session.status = "revoked"
                session.revoked_at = now
                session.updated_at = now
                if session.tenant_id != tenant_id:
                    revoked_other_tenants += 1
                    continue
                revoked_current_tenant += 1
                append_audit_event(
                    self._session,
                    tenant_id=tenant_id,
                    actor_user_id=user_id,
                    action="auth.session.revoke",
                    resource_type="auth_session",
                    resource_id=session.id,
                    context=audit_context,
                    payload={"scope": "password_change"},
                )
            append_audit_event(
                self._session,
                tenant_id=tenant_id,
                actor_user_id=user_id,
                action="auth.password.change",
                resource_type="user",
                resource_id=user_id,
                context=audit_context,
                payload={
                    "session_rotated": True,
                    "revoked_current_tenant_sessions": revoked_current_tenant,
                    "revoked_other_tenant_sessions": revoked_other_tenants,
                },
            )
            return await self._create_session_in_transaction(
                user_id=user_id,
                tenant_id=tenant_id,
                codec=codec,
                session_ttl_seconds=session_ttl_seconds,
                ip_address=ip_address,
                user_agent=user_agent,
                audit_context=audit_context,
                method="password_change",
            )

    async def current_auth(
        self,
        *,
        session_token_digest: str,
        now: datetime,
        idle_ttl_seconds: int,
        touch_interval_seconds: int,
    ) -> CurrentAuth | None:
        idle_cutoff = now - timedelta(seconds=idle_ttl_seconds)
        touch_cutoff = now - timedelta(seconds=touch_interval_seconds)
        async with self._session.begin():
            row = (
                await self._session.execute(
                    select(AuthSessions, Users, Memberships, Tenants)
                    .join(Users, AuthSessions.user_id == Users.id)
                    .join(
                        Memberships,
                        and_(
                            Memberships.tenant_id == AuthSessions.tenant_id,
                            Memberships.user_id == AuthSessions.user_id,
                        ),
                    )
                    .join(Tenants, AuthSessions.tenant_id == Tenants.id)
                    .where(
                        AuthSessions.token_hash == session_token_digest,
                        AuthSessions.status == "active",
                        AuthSessions.expires_at > now,
                        AuthSessions.last_seen_at.is_not(None),
                        AuthSessions.last_seen_at > idle_cutoff,
                        Users.status == "active",
                        Memberships.status == "active",
                        Tenants.status == "active",
                    )
                    .with_for_update(of=AuthSessions)
                )
            ).first()
            if row is None:
                await self._session.execute(
                    update(AuthSessions)
                    .where(
                        AuthSessions.token_hash == session_token_digest,
                        AuthSessions.status == "active",
                        (
                            (AuthSessions.expires_at <= now)
                            | (AuthSessions.last_seen_at.is_(None))
                            | (AuthSessions.last_seen_at <= idle_cutoff)
                        ),
                    )
                    .values(status="expired", updated_at=now)
                )
                return None
            session, user, membership, tenant = row
            await bind_active_transaction_tenant(self._session, tenant.id)
            if session.last_seen_at is None or _as_utc(session.last_seen_at) <= touch_cutoff:
                session.last_seen_at = now
                session.updated_at = now
            return CurrentAuth(
                session_id=session.id,
                user_id=user.id,
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                user_email=user.email,
                membership_id=membership.id,
                role=membership.role,
                password_change_required=bool(user.password_change_required),
                csrf_token_hash=session.csrf_token_hash,
                session_token_digest=session.token_hash,
            )

    async def revoke_session(
        self,
        *,
        session_token_digest: str,
        now: datetime,
        audit_context: AuditContext,
    ) -> None:
        async with self._session.begin():
            session = (
                await self._session.execute(
                    select(AuthSessions)
                    .where(
                        AuthSessions.token_hash == session_token_digest,
                        AuthSessions.status == "active",
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if session is None:
                return
            await bind_active_transaction_tenant(self._session, session.tenant_id)
            session.status = "revoked"
            session.revoked_at = now
            session.updated_at = now
            append_audit_event(
                self._session,
                tenant_id=session.tenant_id,
                actor_user_id=session.user_id,
                action="auth.session.revoke",
                resource_type="auth_session",
                resource_id=session.id,
                context=audit_context,
                payload={"scope": "current"},
            )

    async def list_user_sessions(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        now: datetime,
        idle_ttl_seconds: int,
    ) -> tuple[UserSessionRecord, ...]:
        idle_cutoff = now - timedelta(seconds=idle_ttl_seconds)
        bind_session_tenant(self._session, tenant_id)
        async with self._session.begin():
            await self._session.execute(
                update(AuthSessions)
                .where(
                    AuthSessions.tenant_id == tenant_id,
                    AuthSessions.user_id == user_id,
                    AuthSessions.status == "active",
                    (
                        (AuthSessions.expires_at <= now)
                        | (AuthSessions.last_seen_at.is_(None))
                        | (AuthSessions.last_seen_at <= idle_cutoff)
                    ),
                )
                .values(status="expired", updated_at=now)
            )
            rows = tuple(
                (
                    await self._session.execute(
                        select(AuthSessions)
                        .where(
                            AuthSessions.tenant_id == tenant_id,
                            AuthSessions.user_id == user_id,
                            AuthSessions.status == "active",
                            AuthSessions.expires_at > now,
                            AuthSessions.last_seen_at > idle_cutoff,
                        )
                        .order_by(AuthSessions.last_seen_at.desc(), AuthSessions.id)
                    )
                ).scalars()
            )
            return tuple(
                UserSessionRecord(
                    session_id=row.id,
                    created_at=_as_utc(row.created_at),
                    last_seen_at=_as_utc(row.last_seen_at),
                    expires_at=_as_utc(row.expires_at),
                    ip_address=str(row.ip_address) if row.ip_address is not None else None,
                    user_agent=row.user_agent,
                )
                for row in rows
                if row.last_seen_at is not None
            )

    async def revoke_user_session(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        now: datetime,
        audit_context: AuditContext,
    ) -> bool:
        bind_session_tenant(self._session, tenant_id)
        async with self._session.begin():
            session = (
                await self._session.execute(
                    select(AuthSessions)
                    .where(
                        AuthSessions.tenant_id == tenant_id,
                        AuthSessions.user_id == user_id,
                        AuthSessions.id == session_id,
                        AuthSessions.status == "active",
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if session is None:
                return False
            session.status = "revoked"
            session.revoked_at = now
            session.updated_at = now
            append_audit_event(
                self._session,
                tenant_id=tenant_id,
                actor_user_id=user_id,
                action="auth.session.revoke",
                resource_type="auth_session",
                resource_id=session.id,
                context=audit_context,
                payload={"scope": "other"},
            )
            return True

    async def _create_session_in_transaction(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        codec: OpaqueTokenCodec,
        session_ttl_seconds: int,
        ip_address: str | None,
        user_agent: str | None,
        audit_context: AuditContext,
        consume_one_time_credential: bool = False,
        method: str = "password",
    ) -> SessionRecord:
        issued_session: IssuedOpaqueToken = codec.issue("session")
        issued_csrf: IssuedOpaqueToken = codec.issue("csrf")
        now = datetime.now(UTC)
        if consume_one_time_credential:
            user = (
                await self._session.execute(
                    select(Users)
                    .where(Users.id == user_id, Users.status == "active")
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                user is None
                or not user.password_change_required
                or user.credential_expires_at is None
                or _as_utc(user.credential_expires_at) <= now
                or user.credential_used_at is not None
            ):
                raise OneTimeCredentialUnavailable
            user.credential_used_at = now
        expires_at = now + timedelta(seconds=session_ttl_seconds)
        session = AuthSessions(
            user_id=user_id,
            tenant_id=tenant_id,
            token_hash=issued_session.digest,
            csrf_token_hash=issued_csrf.digest,
            status="active",
            expires_at=expires_at,
            last_seen_at=now,
            ip_address=ip_address,
            user_agent=user_agent[:512] if user_agent else None,
        )
        self._session.add(session)
        await self._session.flush()
        append_audit_event(
            self._session,
            tenant_id=tenant_id,
            actor_user_id=user_id,
            action="auth.session.create",
            resource_type="auth_session",
            resource_id=session.id,
            context=audit_context,
            payload={"method": method},
        )
        return SessionRecord(
            session_id=session.id,
            user_id=user_id,
            tenant_id=tenant_id,
            expires_at=expires_at,
            session_token=issued_session.plaintext.get_secret_value(),
            csrf_token=issued_csrf.plaintext.get_secret_value(),
        )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _integrity_sqlstate(error: IntegrityError) -> str | None:
    """Read PostgreSQL SQLSTATE without depending on a specific asyncpg wrapper."""

    original = error.orig
    direct = getattr(original, "sqlstate", None)
    if isinstance(direct, str):
        return direct
    cause = getattr(original, "__cause__", None)
    nested = getattr(cause, "sqlstate", None)
    return nested if isinstance(nested, str) else None


__all__ = [
    "AuthRepositoryPort",
    "CurrentAuth",
    "CurrentPasswordInvalid",
    "LoginRecord",
    "OneTimeCredentialUnavailable",
    "RegistrationConflict",
    "SQLAuthRepository",
    "SessionNotFound",
    "SessionRecord",
    "TenantSelectionRequired",
    "UserSessionRecord",
]
