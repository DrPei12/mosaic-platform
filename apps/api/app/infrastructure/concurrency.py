from __future__ import annotations

import asyncio
import re
import secrets
from collections.abc import Awaitable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol, Self, TypeVar, cast
from uuid import UUID

RESOURCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,199}$")
_DEFAULT_RETRY_AFTER_SECONDS = 2.0
_DEFAULT_RENEWAL_FRACTION = 1 / 3

ACQUIRE_SCRIPT = """
-- mosaic:lease:acquire
local clock = redis.call('TIME')
local now_ms = (clock[1] * 1000) + math.floor(clock[2] / 1000)
local ttl_ms = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
  return 0
end
redis.call('ZADD', KEYS[1], now_ms + ttl_ms, ARGV[1])
redis.call('PEXPIRE', KEYS[1], ttl_ms * 2)
return 1
""".strip()

RENEW_SCRIPT = """
-- mosaic:lease:renew
local clock = redis.call('TIME')
local now_ms = (clock[1] * 1000) + math.floor(clock[2] / 1000)
local ttl_ms = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if redis.call('ZSCORE', KEYS[1], ARGV[1]) == false then
  return 0
end
redis.call('ZADD', KEYS[1], now_ms + ttl_ms, ARGV[1])
redis.call('PEXPIRE', KEYS[1], ttl_ms * 2)
return 1
""".strip()

RELEASE_SCRIPT = """
-- mosaic:lease:release
local removed = redis.call('ZREM', KEYS[1], ARGV[1])
if redis.call('ZCARD', KEYS[1]) == 0 then
  redis.call('DEL', KEYS[1])
end
return removed
""".strip()


class AsyncRedisScriptClient(Protocol):
    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: Any,
    ) -> Awaitable[Any]: ...


class ConcurrencySaturated(RuntimeError):
    """A durable job must be retried because its configured permit is busy."""

    code = "CONCURRENCY_SATURATED"
    retryable = True

    def __init__(self, *, retry_after_seconds: float = _DEFAULT_RETRY_AFTER_SECONDS) -> None:
        if retry_after_seconds <= 0:
            raise ValueError("retry_after_seconds must be positive")
        self.retry_after_seconds = retry_after_seconds
        super().__init__("configured concurrency is saturated")


class ConcurrencyUnavailable(RuntimeError):
    """Redis admission state could not be read or updated."""

    code = "CONCURRENCY_UNAVAILABLE"
    retryable = True

    def __init__(self) -> None:
        super().__init__("concurrency admission is unavailable")


class ConcurrencyLeaseLost(RuntimeError):
    """A worker lost its Redis lease while a Provider operation was running."""

    code = "CONCURRENCY_LEASE_LOST"
    retryable = False

    def __init__(self) -> None:
        super().__init__("concurrency lease was lost during Provider execution")


@dataclass(slots=True)
class RedisLease:
    _semaphore: RedisLeaseSemaphore
    key: str
    token: str
    ttl_ms: int
    _active: bool = True

    async def renew(self) -> bool:
        if not self._active:
            return False
        try:
            renewed = await self._semaphore._renew(self.key, self.token, self.ttl_ms)
        except Exception:
            _record_permit_loss(self.key)
            self._active = False
            raise
        if not renewed:
            self._active = False
            _record_permit_loss(self.key)
        return renewed

    async def release(self) -> bool:
        if not self._active:
            return False
        self._active = False
        try:
            released = await self._semaphore._release(self.key, self.token)
        except Exception:
            _record_permit_loss(self.key)
            raise
        if not released:
            _record_permit_loss(self.key)
        return released

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.release()


_ResultT = TypeVar("_ResultT")


class RedisLeaseGuard:
    """Renew a set of leases while one Provider operation is in flight.

    The guard deliberately owns release. If the process crashes, Redis TTLs
    remove the sorted-set entries; if the process stays alive but renewal is
    lost, the in-flight operation is cancelled and the caller can preserve its
    at-least-once uncertainty state instead of running outside the permit.
    """

    __slots__ = (
        "_leases",
        "_lost",
        "_renew_interval_seconds",
        "_renew_task",
        "_stopped",
    )

    def __init__(
        self,
        leases: Sequence[RedisLease],
        *,
        renewal_interval_seconds: float | None = None,
    ) -> None:
        if not leases:
            raise ValueError("at least one Redis lease is required")
        self._leases = tuple(leases)
        default_interval = min(
            lease.ttl_ms / 1000 * _DEFAULT_RENEWAL_FRACTION for lease in self._leases
        )
        interval = (
            min(renewal_interval_seconds, default_interval)
            if renewal_interval_seconds is not None
            else default_interval
        )
        if interval <= 0:
            raise ValueError("renewal_interval_seconds must be positive")
        self._renew_interval_seconds = interval
        self._stopped = asyncio.Event()
        self._lost = asyncio.Event()
        self._renew_task: asyncio.Task[None] | None = None

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    async def __aenter__(self) -> Self:
        if self._renew_task is not None:
            raise RuntimeError("RedisLeaseGuard cannot be entered twice")
        self._renew_task = asyncio.create_task(self._renew_loop())
        return self

    async def __aexit__(self, *_: object) -> None:
        self._stopped.set()
        renew_task = self._renew_task
        if renew_task is not None:
            renew_task.cancel()
            with suppress(asyncio.CancelledError):
                await renew_task
        for lease in reversed(self._leases):
            with suppress(Exception):
                await lease.release()

    async def start(self) -> None:
        await self.__aenter__()

    async def close(self) -> None:
        await self.__aexit__(None, None, None)

    async def run(self, operation: Awaitable[_ResultT]) -> _ResultT:
        """Run an operation and abort it if lease renewal reports a loss."""

        if self._renew_task is None:
            raise RuntimeError("RedisLeaseGuard must be used as an async context manager")
        operation_task = asyncio.ensure_future(operation)
        lost_task = asyncio.create_task(self._lost.wait())
        done, _ = await asyncio.wait(
            (operation_task, lost_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if operation_task in done:
            lost_task.cancel()
            with suppress(asyncio.CancelledError):
                await lost_task
            return await operation_task

        operation_task.cancel()
        with suppress(asyncio.CancelledError):
            await operation_task
        raise ConcurrencyLeaseLost()

    async def _renew_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=self._renew_interval_seconds,
                )
                return
            except TimeoutError:
                pass
            for lease in self._leases:
                try:
                    if not await lease.renew():
                        self._lost.set()
                        return
                except Exception:  # noqa: BLE001 - lease loss is fail-closed
                    self._lost.set()
                    return


class RedisLeaseSemaphore:
    """A crash-recoverable distributed semaphore backed by Redis leases.

    Redis is coordination state only. Callers must still persist the accepted
    job and its terminal status in PostgreSQL.
    """

    __slots__ = ("_client", "_environment")

    def __init__(self, client: AsyncRedisScriptClient, *, environment: str) -> None:
        if not RESOURCE_PATTERN.fullmatch(environment):
            raise ValueError("environment contains unsupported Redis key characters")
        self._client = client
        self._environment = environment

    async def acquire(
        self,
        resource: str,
        *,
        limit: int,
        ttl_seconds: float,
    ) -> RedisLease | None:
        key = self.key_for(resource)
        if limit < 1:
            raise ValueError("limit must be at least 1")
        ttl_ms = self._ttl_ms(ttl_seconds)
        token = secrets.token_urlsafe(24)
        try:
            result = await self._client.eval(ACQUIRE_SCRIPT, 1, key, token, limit, ttl_ms)
        except Exception:
            _record_permit_loss(resource)
            raise
        if int(cast(int | bytes | str, result)) != 1:
            _record_permit_saturation(resource)
            return None
        return RedisLease(self, key, token, ttl_ms)

    def key_for(self, resource: str) -> str:
        if not RESOURCE_PATTERN.fullmatch(resource):
            raise ValueError("resource contains unsupported Redis key characters")
        return f"mosaic:{self._environment}:concurrency:{resource}"

    async def _renew(self, key: str, token: str, ttl_ms: int) -> bool:
        result = await self._client.eval(RENEW_SCRIPT, 1, key, token, ttl_ms)
        return int(cast(int | bytes | str, result)) == 1

    async def _release(self, key: str, token: str) -> bool:
        result = await self._client.eval(RELEASE_SCRIPT, 1, key, token)
        return int(cast(int | bytes | str, result)) == 1

    @staticmethod
    def _ttl_ms(ttl_seconds: float) -> int:
        if ttl_seconds < 1 or ttl_seconds > 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")
        return int(ttl_seconds * 1000)


def deployment_resource(deployment_id: UUID) -> str:
    """Return the explicit deployment-scoped permit resource."""

    return f"deployment:{deployment_id}"


def tenant_deployment_resource(tenant_id: UUID, deployment_id: UUID) -> str:
    """Return the explicit tenant+deployment permit resource."""

    return f"tenant:{tenant_id}:deployment:{deployment_id}"


def _resource_from_lease_key(key: str) -> str:
    return key.split(":concurrency:", 1)[-1]


def _record_permit_loss(resource_or_key: str) -> None:
    from app.observability.metrics import record_redis_permit_outcome

    record_redis_permit_outcome(
        resource=_resource_from_lease_key(resource_or_key),
        outcome="loss",
    )


def _record_permit_saturation(resource: str) -> None:
    from app.observability.metrics import record_redis_permit_outcome

    record_redis_permit_outcome(resource=resource, outcome="saturation")


def stream_global_resource() -> str:
    """Return the global HTTP chat-stream permit resource."""

    return "chat-stream:global"


def stream_tenant_resource(tenant_id: UUID) -> str:
    """Return the tenant-scoped HTTP chat-stream permit resource."""

    return f"chat-stream:tenant:{tenant_id}"


async def acquire_chat_stream_admission(
    semaphore: RedisLeaseSemaphore,
    *,
    tenant_id: UUID,
    tenant_limit: int,
    global_limit: int,
    ttl_seconds: float,
    renewal_interval_seconds: float | None = None,
) -> RedisLeaseGuard | None:
    """Acquire global and tenant stream permits, releasing partial state safely."""

    try:
        global_lease = await semaphore.acquire(
            stream_global_resource(),
            limit=global_limit,
            ttl_seconds=ttl_seconds,
        )
    except Exception as exc:
        raise ConcurrencyUnavailable() from exc
    if global_lease is None:
        return None

    try:
        tenant_lease = await semaphore.acquire(
            stream_tenant_resource(tenant_id),
            limit=tenant_limit,
            ttl_seconds=ttl_seconds,
        )
    except Exception as exc:
        with suppress(Exception):
            await global_lease.release()
        raise ConcurrencyUnavailable() from exc
    if tenant_lease is None:
        with suppress(Exception):
            await global_lease.release()
        return None

    return RedisLeaseGuard(
        (global_lease, tenant_lease),
        renewal_interval_seconds=renewal_interval_seconds,
    )


class RedisChatStreamAdmission:
    """Configured tenant/global Redis admission for one SSE connection."""

    __slots__ = (
        "_global_limit",
        "_renewal_interval_seconds",
        "_semaphore",
        "_tenant_limit",
        "_ttl_seconds",
    )

    def __init__(
        self,
        semaphore: RedisLeaseSemaphore,
        *,
        tenant_limit: int,
        global_limit: int,
        ttl_seconds: float,
        renewal_interval_seconds: float | None = None,
    ) -> None:
        if tenant_limit < 1 or global_limit < 1:
            raise ValueError("stream limits must be at least 1")
        if ttl_seconds < 1 or ttl_seconds > 3600:
            raise ValueError("stream TTL must be between 1 and 3600 seconds")
        if renewal_interval_seconds is not None and renewal_interval_seconds <= 0:
            raise ValueError("stream renewal interval must be positive")
        self._semaphore = semaphore
        self._tenant_limit = tenant_limit
        self._global_limit = global_limit
        self._ttl_seconds = ttl_seconds
        self._renewal_interval_seconds = renewal_interval_seconds

    async def acquire(self, *, tenant_id: UUID) -> RedisLeaseGuard | None:
        return await acquire_chat_stream_admission(
            self._semaphore,
            tenant_id=tenant_id,
            tenant_limit=self._tenant_limit,
            global_limit=self._global_limit,
            ttl_seconds=self._ttl_seconds,
            renewal_interval_seconds=self._renewal_interval_seconds,
        )


async def acquire_deployment_admission(
    semaphore: RedisLeaseSemaphore,
    *,
    tenant_id: UUID,
    deployment_id: UUID,
    limit: int,
    ttl_seconds: float,
    renewal_interval_seconds: float | None = None,
) -> RedisLeaseGuard | None:
    """Acquire the global deployment and tenant+deployment permits.

    The deployment record has one limit, so both explicit dimensions use that
    accepted limit. The global lease enforces the deployment cap; the scoped
    lease makes tenant ownership part of the admission identity and prevents
    a future shared-resource collision from crossing tenant boundaries.
    """

    try:
        deployment_lease = await semaphore.acquire(
            deployment_resource(deployment_id),
            limit=limit,
            ttl_seconds=ttl_seconds,
        )
    except Exception as exc:
        raise ConcurrencyUnavailable() from exc
    if deployment_lease is None:
        return None

    try:
        tenant_lease = await semaphore.acquire(
            tenant_deployment_resource(tenant_id, deployment_id),
            limit=limit,
            ttl_seconds=ttl_seconds,
        )
    except Exception as exc:
        with suppress(Exception):
            await deployment_lease.release()
        raise ConcurrencyUnavailable() from exc
    if tenant_lease is None:
        with suppress(Exception):
            await deployment_lease.release()
        return None

    return RedisLeaseGuard(
        (deployment_lease, tenant_lease),
        renewal_interval_seconds=renewal_interval_seconds,
    )


__all__ = [
    "ACQUIRE_SCRIPT",
    "RELEASE_SCRIPT",
    "RENEW_SCRIPT",
    "ConcurrencyLeaseLost",
    "ConcurrencySaturated",
    "ConcurrencyUnavailable",
    "RedisChatStreamAdmission",
    "RedisLease",
    "RedisLeaseGuard",
    "RedisLeaseSemaphore",
    "acquire_chat_stream_admission",
    "acquire_deployment_admission",
    "deployment_resource",
    "stream_global_resource",
    "stream_tenant_resource",
    "tenant_deployment_resource",
]
