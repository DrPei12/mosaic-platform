import asyncio
from collections import deque
from uuid import UUID

import pytest

from app.infrastructure.concurrency import (
    ACQUIRE_SCRIPT,
    RELEASE_SCRIPT,
    RENEW_SCRIPT,
    RedisLeaseSemaphore,
    acquire_chat_stream_admission,
    acquire_deployment_admission,
    deployment_resource,
    stream_global_resource,
    stream_tenant_resource,
    tenant_deployment_resource,
)


class ScriptClient:
    def __init__(self, *results: int) -> None:
        self.results = deque(results)
        self.calls: list[tuple[str, int, tuple[str | int, ...]]] = []

    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str | int,
    ) -> object:
        self.calls.append((script, numkeys, keys_and_args))
        return self.results.popleft()


@pytest.mark.asyncio
async def test_acquire_renew_and_release_use_atomic_scripts() -> None:
    client = ScriptClient(1, 1, 1)
    semaphore = RedisLeaseSemaphore(client, environment="production")

    lease = await semaphore.acquire(
        "tenant:tenant-id:deployment:deployment-id",
        limit=4,
        ttl_seconds=30,
    )

    assert lease is not None
    assert await lease.renew() is True
    assert await lease.release() is True
    assert [call[0] for call in client.calls] == [
        ACQUIRE_SCRIPT,
        RENEW_SCRIPT,
        RELEASE_SCRIPT,
    ]
    key = "mosaic:production:concurrency:tenant:tenant-id:deployment:deployment-id"
    assert client.calls[0][1:] == (1, (key, lease.token, 4, 30_000))
    assert client.calls[1][1:] == (1, (key, lease.token, 30_000))
    assert client.calls[2][1:] == (1, (key, lease.token))


@pytest.mark.asyncio
async def test_capacity_rejection_returns_no_lease() -> None:
    client = ScriptClient(0)
    semaphore = RedisLeaseSemaphore(client, environment="production")

    assert (
        await semaphore.acquire("deployment:busy", limit=1, ttl_seconds=30)
        is None
    )


@pytest.mark.asyncio
async def test_deployment_admission_uses_global_and_tenant_scoped_permits() -> None:
    client = ScriptClient(1, 1, 1, 1)
    semaphore = RedisLeaseSemaphore(client, environment="test")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    deployment_id = UUID("00000000-0000-0000-0000-000000000002")

    admission = await acquire_deployment_admission(
        semaphore,
        tenant_id=tenant_id,
        deployment_id=deployment_id,
        limit=2,
        ttl_seconds=30,
    )

    assert admission is not None
    async with admission:
        pass
    assert client.calls[0][2][0] == semaphore.key_for(deployment_resource(deployment_id))
    assert client.calls[1][2][0] == semaphore.key_for(
        tenant_deployment_resource(tenant_id, deployment_id)
    )
    assert [call[0] for call in client.calls[2:]] == [RELEASE_SCRIPT, RELEASE_SCRIPT]


@pytest.mark.asyncio
async def test_tenant_admission_saturation_releases_global_lease() -> None:
    client = ScriptClient(1, 0, 1)
    semaphore = RedisLeaseSemaphore(client, environment="test")

    admission = await acquire_deployment_admission(
        semaphore,
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        deployment_id=UUID("00000000-0000-0000-0000-000000000002"),
        limit=1,
        ttl_seconds=30,
    )

    assert admission is None
    assert [call[0] for call in client.calls] == [ACQUIRE_SCRIPT, ACQUIRE_SCRIPT, RELEASE_SCRIPT]


@pytest.mark.asyncio
async def test_chat_stream_admission_uses_global_and_tenant_leases() -> None:
    client = ScriptClient(1, 1, 1, 1)
    semaphore = RedisLeaseSemaphore(client, environment="test")
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    admission = await acquire_chat_stream_admission(
        semaphore,
        tenant_id=tenant_id,
        tenant_limit=3,
        global_limit=10,
        ttl_seconds=30,
    )

    assert admission is not None
    await admission.start()
    await admission.close()
    assert client.calls[0][2][0] == semaphore.key_for(stream_global_resource())
    assert client.calls[1][2][0] == semaphore.key_for(stream_tenant_resource(tenant_id))
    assert [call[0] for call in client.calls[2:]] == [RELEASE_SCRIPT, RELEASE_SCRIPT]


@pytest.mark.asyncio
async def test_chat_stream_tenant_saturation_releases_global_lease() -> None:
    client = ScriptClient(1, 0, 1)
    semaphore = RedisLeaseSemaphore(client, environment="test")

    admission = await acquire_chat_stream_admission(
        semaphore,
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        tenant_limit=1,
        global_limit=1,
        ttl_seconds=30,
    )

    assert admission is None
    assert [call[0] for call in client.calls] == [ACQUIRE_SCRIPT, ACQUIRE_SCRIPT, RELEASE_SCRIPT]


@pytest.mark.asyncio
async def test_lease_guard_renews_during_operation_and_releases_afterward() -> None:
    client = ScriptClient(*([1] * 20))
    semaphore = RedisLeaseSemaphore(client, environment="test")
    admission = await acquire_deployment_admission(
        semaphore,
        tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
        deployment_id=UUID("00000000-0000-0000-0000-000000000002"),
        limit=1,
        ttl_seconds=1,
        renewal_interval_seconds=0.01,
    )

    assert admission is not None
    async with admission:
        await admission.run(asyncio.sleep(0.035))
    scripts = [call[0] for call in client.calls]
    assert scripts.count(RENEW_SCRIPT) >= 2
    assert scripts[-2:] == [RELEASE_SCRIPT, RELEASE_SCRIPT]


@pytest.mark.asyncio
async def test_lost_lease_becomes_inactive() -> None:
    client = ScriptClient(1, 0)
    semaphore = RedisLeaseSemaphore(client, environment="production")
    lease = await semaphore.acquire("deployment:one", limit=1, ttl_seconds=30)
    assert lease is not None

    assert await lease.renew() is False
    assert await lease.release() is False
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    ("resource", "limit", "ttl"),
    [
        ("../cross-tenant", 1, 30),
        ("deployment:ok", 0, 30),
        ("deployment:ok", 1, 0.5),
        ("deployment:ok", 1, 3601),
    ],
)
@pytest.mark.asyncio
async def test_invalid_lease_inputs_fail_before_redis(
    resource: str,
    limit: int,
    ttl: float,
) -> None:
    client = ScriptClient()
    semaphore = RedisLeaseSemaphore(client, environment="production")

    with pytest.raises(ValueError):
        await semaphore.acquire(resource, limit=limit, ttl_seconds=ttl)

    assert client.calls == []


def test_scripts_use_redis_time_and_expiring_sorted_set() -> None:
    assert "redis.call('TIME')" in ACQUIRE_SCRIPT
    assert "ZREMRANGEBYSCORE" in ACQUIRE_SCRIPT
    assert "PEXPIRE" in ACQUIRE_SCRIPT
    assert "redis.call('TIME')" in RENEW_SCRIPT
    assert "ZREM" in RELEASE_SCRIPT
