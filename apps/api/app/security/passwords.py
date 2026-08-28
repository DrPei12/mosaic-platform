"""Argon2id password hashing with a deliberately narrow public surface.

The application never stores or logs a plaintext password.  This module owns
the parameters so that a future cost increase can be rolled out centrally;
successful verification can then opportunistically rehash an older value.
"""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher as _Argon2PasswordHasher
from argon2 import Type as Argon2Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.settings import Settings, settings


@dataclass(frozen=True, slots=True)
class PasswordHashParameters:
    """Operational Argon2id parameters, kept in one configuration object."""

    time_cost: int
    memory_cost_kib: int
    parallelism: int
    hash_len: int
    salt_len: int

    @classmethod
    def from_settings(cls, value: Settings) -> PasswordHashParameters:
        return cls(
            time_cost=value.password_hash_time_cost,
            memory_cost_kib=value.password_hash_memory_cost_kib,
            parallelism=value.password_hash_parallelism,
            hash_len=value.password_hash_hash_len,
            salt_len=value.password_hash_salt_len,
        )


class PasswordHasher:
    """Safe Argon2id wrapper used by registration and login."""

    __slots__ = ("_dummy_hash", "_hasher")

    def __init__(self, parameters: PasswordHashParameters | None = None) -> None:
        resolved = parameters or PasswordHashParameters.from_settings(settings)
        self._hasher = _Argon2PasswordHasher(
            time_cost=resolved.time_cost,
            memory_cost=resolved.memory_cost_kib,
            parallelism=resolved.parallelism,
            hash_len=resolved.hash_len,
            salt_len=resolved.salt_len,
            type=Argon2Type.ID,
        )
        # A fixed-format dummy hash keeps unknown-account login timing close to
        # the known-account path without ever comparing against a user value.
        self._dummy_hash = self._hasher.hash("mosaic-invalid-account-password")

    def hash(self, password: str) -> str:
        """Hash a password; callers must not log the returned encoded value."""

        return self._hasher.hash(password)

    def verify(self, encoded_hash: str, password: str) -> bool:
        """Return only a boolean and never leak Argon2 parsing details."""

        try:
            return self._hasher.verify(encoded_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    def verify_or_dummy(self, encoded_hash: str | None, password: str) -> bool:
        """Verify a user hash or an internal dummy hash for timing equalisation."""

        return self.verify(encoded_hash or self._dummy_hash, password)

    def needs_rehash(self, encoded_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(encoded_hash)
        except (InvalidHashError, VerificationError):
            return False

    def __repr__(self) -> str:
        return "PasswordHasher(algorithm='argon2id', parameters=<redacted>)"


__all__ = ["PasswordHashParameters", "PasswordHasher"]
