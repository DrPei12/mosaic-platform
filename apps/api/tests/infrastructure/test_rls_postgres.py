"""Real PostgreSQL proof that a non-owner API role cannot cross tenants."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.audit.writer import AuditContext
from app.auth.repository import SQLAuthRepository
from app.infrastructure.models import (
    AuditEvents,
    AuthSessions,
    Memberships,
    Tenants,
    Users,
    WalletAccounts,
)
from app.security.passwords import PasswordHasher
from app.security.tokens import OpaqueTokenCodec

_RAW_DATABASE_URL = os.environ.get("RLS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _RAW_DATABASE_URL,
    reason="RLS_TEST_DATABASE_URL is required for real PostgreSQL RLS tests",
)


def _database_url() -> str:
    assert _RAW_DATABASE_URL is not None
    if _RAW_DATABASE_URL.startswith("postgresql+asyncpg://"):
        return _RAW_DATABASE_URL
    if _RAW_DATABASE_URL.startswith("postgresql://"):
        return _RAW_DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    raise ValueError("RLS_TEST_DATABASE_URL must use PostgreSQL")


def _upgrade_schema() -> None:
    from app.core.settings import settings

    previous_url = settings.database_url
    settings.database_url = _database_url()
    try:
        root = Path(__file__).parents[2]
        command.upgrade(Config(str(root / "alembic.ini")), "head")
    finally:
        settings.database_url = previous_url


@pytest.mark.asyncio
async def test_non_owner_role_is_bound_to_transaction_tenant() -> None:
    await asyncio.to_thread(_upgrade_schema)
    owner_engine = create_async_engine(_database_url(), poolclass=NullPool)
    owner_sessions = async_sessionmaker(owner_engine, expire_on_commit=False)
    tenant_a = uuid4()
    tenant_b = uuid4()
    role = f"mosaic_rls_{uuid4().hex}"
    password = uuid4().hex + uuid4().hex
    role_engine = None
    role_created = False
    try:
        async with owner_sessions() as session, session.begin():
            session.add_all(
                [
                    Tenants(id=tenant_a, slug=f"rls-a-{tenant_a.hex[:12]}", name="RLS A", status="active", settings={}),
                    Tenants(id=tenant_b, slug=f"rls-b-{tenant_b.hex[:12]}", name="RLS B", status="active", settings={}),
                    WalletAccounts(id=uuid4(), tenant_id=tenant_a, currency="PTS", balance_minor=100, reserved_minor=0, version=0, status="active"),
                    WalletAccounts(id=uuid4(), tenant_id=tenant_b, currency="PTS", balance_minor=200, reserved_minor=0, version=0, status="active"),
                ]
            )
        async with owner_engine.begin() as connection:
            await connection.execute(text(f'CREATE ROLE "{role}" LOGIN PASSWORD \'{password}\''))
            role_created = True
            await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            await connection.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"'))
            await connection.execute(text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"'))

        role_url = owner_engine.url.set(username=role, password=password)
        role_engine = create_async_engine(role_url, poolclass=NullPool)
        role_sessions = async_sessionmaker(role_engine, expire_on_commit=False)

        async with role_sessions() as session, session.begin():
            await session.execute(
                text("SELECT set_config('mosaic.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_a)},
            )
            wallets = tuple((await session.execute(select(WalletAccounts))).scalars())
            assert {wallet.tenant_id for wallet in wallets} == {tenant_a}
            assert (
                await session.execute(
                    select(WalletAccounts.id).where(WalletAccounts.tenant_id == tenant_b)
                )
            ).scalar_one_or_none() is None

        with pytest.raises(DBAPIError):
            async with role_sessions() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('mosaic.tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_a)},
                )
                session.add(
                    WalletAccounts(
                        id=uuid4(),
                        tenant_id=tenant_b,
                        currency="PTS",
                        balance_minor=1,
                        reserved_minor=0,
                        version=0,
                        status="active",
                    )
                )
                await session.flush()
    finally:
        if role_engine is not None:
            await role_engine.dispose()
        if role_created:
            async with owner_engine.begin() as connection:
                await connection.execute(text(f'DROP OWNED BY "{role}"'))
                await connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        async with owner_sessions() as session, session.begin():
            await session.execute(
                delete(WalletAccounts).where(WalletAccounts.tenant_id.in_((tenant_a, tenant_b)))
            )
            await session.execute(delete(Tenants).where(Tenants.id.in_((tenant_a, tenant_b))))
        await owner_engine.dispose()


@pytest.mark.asyncio
async def test_auth_session_audit_binds_tenant_for_non_owner_role() -> None:
    await asyncio.to_thread(_upgrade_schema)
    owner_engine = create_async_engine(_database_url(), poolclass=NullPool)
    owner_sessions = async_sessionmaker(owner_engine, expire_on_commit=False)
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    user_id = uuid4()
    membership_id = uuid4()
    other_membership_id = uuid4()
    other_session_id = uuid4()
    current_password = "current-password-123"
    next_password = "next-password-456"
    hasher = PasswordHasher()
    password_hash = await asyncio.to_thread(hasher.hash, current_password)
    role = f"mosaic_auth_rls_{uuid4().hex}"
    password = uuid4().hex + uuid4().hex
    role_engine = None
    role_created = False
    try:
        async with owner_sessions() as session, session.begin():
            session.add_all(
                [
                    Tenants(
                        id=tenant_id,
                        slug=f"auth-rls-{tenant_id.hex[:12]}",
                        name="Auth RLS",
                        status="active",
                        settings={},
                    ),
                    Tenants(
                        id=other_tenant_id,
                        slug=f"auth-rls-{other_tenant_id.hex[:12]}",
                        name="Auth RLS Other",
                        status="active",
                        settings={},
                    ),
                    Users(
                        id=user_id,
                        email=f"auth-rls-{user_id.hex[:12]}@example.test",
                        password_hash=password_hash,
                        status="active",
                        password_change_required=True,
                        credential_expires_at=datetime.now(UTC) + timedelta(hours=1),
                        credential_used_at=None,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Memberships(
                        id=membership_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        role="owner",
                        status="active",
                    ),
                    Memberships(
                        id=other_membership_id,
                        tenant_id=other_tenant_id,
                        user_id=user_id,
                        role="member",
                        status="active",
                    ),
                ]
            )
            await session.flush()
            session.add(
                AuthSessions(
                    id=other_session_id,
                    tenant_id=other_tenant_id,
                    user_id=user_id,
                    token_hash="a" * 64,
                    csrf_token_hash="b" * 64,
                    status="active",
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                    last_seen_at=datetime.now(UTC),
                    ip_address="127.0.0.1",
                    user_agent="rls-other-tenant",
                )
            )
        async with owner_engine.begin() as connection:
            await connection.execute(text(f'CREATE ROLE "{role}" LOGIN PASSWORD \'{password}\''))
            role_created = True
            await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            await connection.execute(
                text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{role}"')
            )
            await connection.execute(
                text(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
            )

        role_url = owner_engine.url.set(username=role, password=password)
        role_engine = create_async_engine(role_url, poolclass=NullPool)
        role_sessions = async_sessionmaker(role_engine, expire_on_commit=False)
        async with role_sessions() as session:
            codec = OpaqueTokenCodec(SecretStr("r" * 48))
            repository = SQLAuthRepository(session)
            record = await repository.create_session(
                user_id=user_id,
                tenant_id=tenant_id,
                codec=codec,
                session_ttl_seconds=3_600,
                ip_address="127.0.0.1",
                user_agent="rls-test",
                audit_context=AuditContext(),
            )
            auth = await repository.current_auth(
                session_token_digest=codec.digest(record.session_token, purpose="session"),
                now=datetime.now(UTC),
                idle_ttl_seconds=1_800,
                touch_interval_seconds=300,
            )
            assert auth is not None
            assert auth.password_change_required is True
            rotated = await repository.change_password(
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=record.session_id,
                current_password=current_password,
                new_password_hash=await asyncio.to_thread(hasher.hash, next_password),
                hasher=hasher,
                codec=codec,
                session_ttl_seconds=3_600,
                ip_address="127.0.0.1",
                user_agent="rls-test-rotated",
                audit_context=AuditContext(),
            )

        async with owner_sessions() as session, session.begin():
            stored_session = await session.get(AuthSessions, record.session_id)
            other_session = await session.get(AuthSessions, other_session_id)
            rotated_session = await session.get(AuthSessions, rotated.session_id)
            audit_event = (
                await session.execute(
                    select(AuditEvents).where(
                        AuditEvents.tenant_id == tenant_id,
                        AuditEvents.resource_id == record.session_id,
                        AuditEvents.action == "auth.session.create",
                    )
                )
            ).scalar_one()
            assert stored_session is not None
            assert stored_session.tenant_id == tenant_id
            assert stored_session.status == "revoked"
            assert other_session is not None
            assert other_session.status == "revoked"
            assert rotated_session is not None
            assert rotated_session.status == "active"
            assert audit_event.actor_user_id == user_id
            password_event = (
                await session.execute(
                    select(AuditEvents).where(
                        AuditEvents.tenant_id == tenant_id,
                        AuditEvents.action == "auth.password.change",
                    )
                )
            ).scalar_one()
            assert password_event.payload["revoked_current_tenant_sessions"] == 1
            assert password_event.payload["revoked_other_tenant_sessions"] == 1
            assert (
                await session.execute(
                    select(AuditEvents.id).where(AuditEvents.tenant_id == other_tenant_id)
                )
            ).scalar_one_or_none() is None
    finally:
        if role_engine is not None:
            await role_engine.dispose()
        if role_created:
            async with owner_engine.begin() as connection:
                await connection.execute(text(f'DROP OWNED BY "{role}"'))
                await connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        async with owner_sessions() as session, session.begin():
            tenant_ids = (tenant_id, other_tenant_id)
            await session.execute(delete(AuditEvents).where(AuditEvents.tenant_id.in_(tenant_ids)))
            await session.execute(delete(AuthSessions).where(AuthSessions.tenant_id.in_(tenant_ids)))
            await session.execute(delete(Memberships).where(Memberships.tenant_id.in_(tenant_ids)))
            await session.execute(delete(Users).where(Users.id == user_id))
            await session.execute(delete(Tenants).where(Tenants.id.in_(tenant_ids)))
        await owner_engine.dispose()
