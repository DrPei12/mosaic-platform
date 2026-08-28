"""Create and reset invitation-only accounts from a protected operator host.

The command never accepts a caller-provided password.  It generates a
single-use credential, stores only its Argon2id hash, and prints the plaintext
exactly once for the operator to deliver out of band.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import secrets
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.audit.writer import AuditContext, append_audit_event
from app.infrastructure.database import dispose_engine, session_factory
from app.infrastructure.models import (
    AuthSessions,
    LedgerEntries,
    Memberships,
    ProductModels,
    TenantModelEntitlements,
    Tenants,
    Users,
    WalletAccounts,
)
from app.security.passwords import PasswordHasher

ONE_TIME_CREDENTIAL_TTL = timedelta(hours=24)
PTS_CURRENCY = "PTS"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?$")
_ROLES = frozenset({"owner", "admin", "member", "billing_viewer"})


@dataclass(frozen=True, slots=True, repr=False)
class OperatorCredential:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    account: str
    value: str
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            "OperatorCredential("
            f"user_id={self.user_id!r}, tenant_id={self.tenant_id!r}, "
            f"account={self.account!r}, expires_at={self.expires_at!r}, "
            "value=<redacted>)"
        )


def _required_text(value: str, *, field: str, max_length: int) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{field} must not be blank")
    if len(candidate) > max_length:
        raise ValueError(f"{field} is too long")
    return candidate


def _normalise_email(value: str) -> str:
    candidate = _required_text(value, field="account", max_length=320).casefold()
    if _EMAIL_RE.fullmatch(candidate) is None:
        raise ValueError("account is invalid")
    return candidate


def _normalise_slug(value: str) -> str:
    candidate = _required_text(value, field="tenant_slug", max_length=120).casefold()
    if _SLUG_RE.fullmatch(candidate) is None:
        raise ValueError("tenant_slug is invalid")
    return candidate


def _validate_operator_inputs(
    *, operator_subject: str, reason: str, role: str | None = None
) -> tuple[str, str, str | None]:
    subject = _required_text(operator_subject, field="operator_subject", max_length=255)
    audit_reason = _required_text(reason, field="reason", max_length=1_000)
    if role is not None:
        role = _required_text(role, field="role", max_length=32)
        if role not in _ROLES:
            raise ValueError("role is invalid")
    return subject, audit_reason, role


def _new_credential() -> str:
    return secrets.token_urlsafe(32)


def _operator_audit_context(operator_subject: str) -> AuditContext:
    return AuditContext(user_agent=f"operator-cli:{operator_subject}"[:512])


def _operator_payload(*, operator_subject: str, reason: str, role: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "operator_subject": operator_subject,
        "reason": reason,
    }
    if role is not None:
        payload["role"] = role
    return payload


async def _ensure_pts_wallet(session: AsyncSession, tenant_id: uuid.UUID) -> WalletAccounts:
    wallet = (
        await session.execute(
            select(WalletAccounts)
            .where(
                WalletAccounts.tenant_id == tenant_id,
                WalletAccounts.currency == PTS_CURRENCY,
                WalletAccounts.status == "active",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if wallet is not None:
        return wallet
    wallet = WalletAccounts(
        tenant_id=tenant_id,
        currency=PTS_CURRENCY,
        balance_minor=0,
        reserved_minor=0,
        version=0,
        status="active",
    )
    session.add(wallet)
    await session.flush()
    return wallet


async def _grant_initial_points(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    wallet: WalletAccounts,
    amount_minor: int,
) -> None:
    if amount_minor < 0:
        raise ValueError("initial_points_minor must be non-negative")
    if amount_minor == 0:
        return
    wallet.balance_minor = int(wallet.balance_minor) + amount_minor
    wallet.version = int(wallet.version) + 1
    session.add(
        LedgerEntries(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            wallet_account_id=wallet.id,
            reservation_id=None,
            entry_type="credit",
            amount_minor=amount_minor,
            currency=PTS_CURRENCY,
            reference_type="operator_grant",
            reference_id=tenant_id,
            idempotency_key=f"operator-grant:{tenant_id}:{wallet.version}",
            created_at=datetime.now(UTC),
        )
    )


async def create(
    *,
    account: str,
    tenant_slug: str,
    tenant_name: str | None,
    operator_subject: str,
    reason: str,
    role: str = "owner",
    initial_points_minor: int = 0,
) -> OperatorCredential:
    """Create an invited account and return its one-time 24-hour credential."""

    email = _normalise_email(account)
    slug = _normalise_slug(tenant_slug)
    subject, audit_reason, validated_role = _validate_operator_inputs(
        operator_subject=operator_subject,
        reason=reason,
        role=role,
    )
    assert validated_role is not None
    if initial_points_minor < 0:
        raise ValueError("initial_points_minor must be non-negative")

    credential = _new_credential()
    now = datetime.now(UTC)
    expires_at = now + ONE_TIME_CREDENTIAL_TTL
    password_hash = PasswordHasher().hash(credential)
    audit_context = _operator_audit_context(subject)

    async with session_factory() as session, session.begin():
        user = (
            await session.execute(select(Users).where(Users.email == email).with_for_update())
        ).scalar_one_or_none()
        if user is not None:
            raise ValueError("account already exists")

        tenant = (
            await session.execute(select(Tenants).where(Tenants.slug == slug).with_for_update())
        ).scalar_one_or_none()
        new_tenant = tenant is None
        if new_tenant:
            name = _required_text(tenant_name or "", field="tenant_name", max_length=200)
            tenant = Tenants(slug=slug, name=name, status="active", settings={})
            session.add(tenant)
            await session.flush()
        assert tenant is not None

        user = Users(
            email=email,
            password_hash=password_hash,
            display_name=email.split("@", 1)[0][:160],
            status="active",
            failed_login_count=0,
            password_change_required=True,
            credential_expires_at=expires_at,
            credential_used_at=None,
        )
        session.add(user)
        await session.flush()
        membership = Memberships(
            tenant_id=tenant.id,
            user_id=user.id,
            role=validated_role,
            status="active",
        )
        session.add(membership)
        if new_tenant:
            active_models = (
                await session.execute(select(ProductModels.id).where(ProductModels.status == "active"))
            ).scalars()
            session.add_all(
                TenantModelEntitlements(
                    tenant_id=tenant.id,
                    product_model_id=model_id,
                    enabled=True,
                    config={},
                )
                for model_id in active_models
            )
        wallet = await _ensure_pts_wallet(session, tenant.id)
        await _grant_initial_points(
            session,
            tenant_id=tenant.id,
            wallet=wallet,
            amount_minor=initial_points_minor,
        )
        await session.flush()
        append_audit_event(
            session,
            tenant_id=tenant.id,
            actor_user_id=None,
            action="auth.operator.account_create",
            resource_type="user",
            resource_id=user.id,
            context=audit_context,
            payload={
                **_operator_payload(
                    operator_subject=subject,
                    reason=audit_reason,
                    role=validated_role,
                ),
                "tenant_slug": tenant.slug,
                "currency": PTS_CURRENCY,
            },
        )
        return OperatorCredential(
            user_id=user.id,
            tenant_id=tenant.id,
            account=email,
            value=credential,
            expires_at=expires_at,
        )


async def reset(
    *,
    account: str,
    operator_subject: str,
    reason: str,
) -> OperatorCredential:
    """Rotate an invited account's credential and revoke every old session."""

    email = _normalise_email(account)
    subject, audit_reason, _ = _validate_operator_inputs(
        operator_subject=operator_subject,
        reason=reason,
    )
    credential = _new_credential()
    now = datetime.now(UTC)
    expires_at = now + ONE_TIME_CREDENTIAL_TTL
    password_hash = PasswordHasher().hash(credential)
    audit_context = _operator_audit_context(subject)

    async with session_factory() as session, session.begin():
        user = (
            await session.execute(select(Users).where(Users.email == email).with_for_update())
        ).scalar_one_or_none()
        if user is None or user.status != "active":
            raise ValueError("active account was not found")
        memberships = tuple(
            (
                await session.execute(
                    select(Memberships, Tenants)
                    .join(Tenants, Memberships.tenant_id == Tenants.id)
                    .where(
                        Memberships.user_id == user.id,
                        Memberships.status == "active",
                        Tenants.status == "active",
                    )
                )
            ).all()
        )
        if not memberships:
            raise ValueError("active account tenant was not found")

        user.password_hash = password_hash
        user.password_changed_at = now
        user.password_change_required = True
        user.credential_expires_at = expires_at
        user.credential_used_at = None
        user.failed_login_count = 0
        user.locked_until = None

        sessions = tuple(
            (
                await session.execute(
                    select(AuthSessions)
                    .where(AuthSessions.user_id == user.id, AuthSessions.status == "active")
                    .with_for_update()
                )
            ).scalars()
        )
        for auth_session in sessions:
            auth_session.status = "revoked"
            auth_session.revoked_at = now
            auth_session.updated_at = now
            append_audit_event(
                session,
                tenant_id=auth_session.tenant_id,
                actor_user_id=None,
                action="auth.operator.session_revoke",
                resource_type="auth_session",
                resource_id=auth_session.id,
                context=audit_context,
                payload=_operator_payload(operator_subject=subject, reason=audit_reason),
            )
        for _membership, tenant in memberships:
            append_audit_event(
                session,
                tenant_id=tenant.id,
                actor_user_id=None,
                action="auth.operator.credential_reset",
                resource_type="user",
                resource_id=user.id,
                context=audit_context,
                payload=_operator_payload(operator_subject=subject, reason=audit_reason),
            )
        return OperatorCredential(
            user_id=user.id,
            tenant_id=memberships[0][1].id,
            account=email,
            value=credential,
            expires_at=expires_at,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage invitation-only MOSAIC accounts")
    commands = parser.add_subparsers(dest="command", required=True)

    create_parser = commands.add_parser("create")
    create_parser.add_argument("--account", "--email", dest="account", required=True)
    create_parser.add_argument("--tenant-slug", "--tenant", dest="tenant_slug", required=True)
    create_parser.add_argument("--tenant-name")
    create_parser.add_argument("--role", default="owner", choices=sorted(_ROLES))
    create_parser.add_argument("--initial-points-minor", type=int, default=0)
    create_parser.add_argument("--operator-subject", required=True)
    create_parser.add_argument("--reason", required=True)

    reset_parser = commands.add_parser("reset")
    reset_parser.add_argument("--account", "--email", dest="account", required=True)
    reset_parser.add_argument("--operator-subject", required=True)
    reset_parser.add_argument("--reason", required=True)
    return parser


async def _run_and_dispose(args: argparse.Namespace) -> OperatorCredential:
    try:
        if args.command == "create":
            return await create(
                account=args.account,
                tenant_slug=args.tenant_slug,
                tenant_name=args.tenant_name,
                operator_subject=args.operator_subject,
                reason=args.reason,
                role=args.role,
                initial_points_minor=args.initial_points_minor,
            )
        return await reset(
            account=args.account,
            operator_subject=args.operator_subject,
            reason=args.reason,
        )
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(_run_and_dispose(args))
    except ValueError as exc:
        _parser().error(str(exc))
    print(f"account: {result.account}")
    print(f"one-time-credential: {result.value}")
    print(f"expires-at: {result.expires_at.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ONE_TIME_CREDENTIAL_TTL",
    "PTS_CURRENCY",
    "OperatorCredential",
    "create",
    "main",
    "reset",
]
