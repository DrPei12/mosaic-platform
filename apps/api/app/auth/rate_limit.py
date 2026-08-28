"""Fail-closed login admission controls.

The limiter is coordination state only.  Account lockout remains persisted in
PostgreSQL, while Redis prevents a single client from consuming unlimited
password verification work across API replicas.
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol, cast


class RedisRateLimitClient(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...

    async def delete(self, *keys: Any) -> Any: ...


class LoginRateLimiterUnavailable(RuntimeError):
    """Redis could not make an authoritative admission decision."""


class LoginRateLimiter(Protocol):
    async def allow(self, key: str) -> bool: ...

    async def reset(self, key: str) -> None: ...


class FailClosedLoginRateLimiter:
    """Test/deployment fallback that refuses login when no limiter exists."""

    async def allow(self, _: str) -> bool:
        raise LoginRateLimiterUnavailable("login rate limiter is not configured")

    async def reset(self, _: str) -> None:
        return None


_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return count
""".strip()


class RedisLoginRateLimiter:
    """Atomic fixed-window limiter backed by a shared Redis instance."""

    def __init__(
        self,
        client: RedisRateLimitClient,
        *,
        environment: str,
        limit: int,
        window_seconds: int,
    ) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("login rate limit parameters must be positive")
        self._client = client
        self._prefix = f"mosaic:{environment}:auth:login"
        self._limit = limit
        self._window_seconds = window_seconds

    @staticmethod
    def key_material(account: str, client_ip: str | None) -> str:
        material = f"pair\x00{account}\x00{client_ip or '-'}".encode()
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    def key_materials(account: str, client_ip: str | None) -> tuple[str, str, str]:
        """Return independent account, IP, and account+IP limiter keys."""

        ip = client_ip or "-"
        return (
            hashlib.sha256(f"account\x00{account}".encode()).hexdigest(),
            hashlib.sha256(f"ip\x00{ip}".encode()).hexdigest(),
            hashlib.sha256(f"pair\x00{account}\x00{ip}".encode()).hexdigest(),
        )

    def _key(self, material: str) -> str:
        if len(material) != 64 or any(char not in "0123456789abcdef" for char in material):
            raise ValueError("invalid login limiter key")
        return f"{self._prefix}:{material}"

    async def allow(self, key: str) -> bool:
        try:
            result = await self._client.eval(
                _RATE_LIMIT_SCRIPT,
                1,
                self._key(key),
                self._window_seconds,
            )
            return int(cast(str | bytes | int, result)) <= self._limit
        except Exception as exc:
            raise LoginRateLimiterUnavailable("login rate limiter unavailable") from exc

    async def reset(self, key: str) -> None:
        try:
            await self._client.delete(self._key(key))
        except Exception as exc:
            raise LoginRateLimiterUnavailable("login rate limiter unavailable") from exc
