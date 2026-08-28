import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

from pydantic import SecretStr

SESSION_TOKEN_PEPPER_ENV = "MOSAIC_SESSION_TOKEN_PEPPER"
TOKEN_BYTES = 32
MINIMUM_PEPPER_LENGTH = 32
_PLACEHOLDER_MARKERS = ("replace_with", "placeholder")


class SessionTokenConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedOpaqueToken:
    """A plaintext token for one-time delivery plus its persistence-safe digest."""

    plaintext: SecretStr
    digest: str


class OpaqueTokenCodec:
    """Issue high-entropy tokens and hash them with a server-side pepper.

    The token is already resistant to guessing. HMAC additionally prevents a
    database-only compromise from turning stored token digests into reusable
    bearer credentials.
    """

    __slots__ = ("_pepper",)

    def __init__(self, pepper: SecretStr) -> None:
        raw_pepper = pepper.get_secret_value()
        if len(raw_pepper) < MINIMUM_PEPPER_LENGTH or any(
            marker in raw_pepper.casefold() for marker in _PLACEHOLDER_MARKERS
        ):
            raise SessionTokenConfigurationError(
                f"{SESSION_TOKEN_PEPPER_ENV} must contain at least "
                f"{MINIMUM_PEPPER_LENGTH} non-placeholder characters"
            )
        self._pepper = raw_pepper.encode("utf-8")

    def __repr__(self) -> str:
        return "OpaqueTokenCodec(pepper=SecretStr('**********'))"

    @classmethod
    def from_process_environment(cls) -> "OpaqueTokenCodec":
        value = os.environ.get(SESSION_TOKEN_PEPPER_ENV)
        if value is None or not value.strip():
            raise SessionTokenConfigurationError(
                f"{SESSION_TOKEN_PEPPER_ENV} is required in the process environment"
            )
        return cls(SecretStr(value))

    def issue(self, purpose: str) -> IssuedOpaqueToken:
        plaintext = secrets.token_urlsafe(TOKEN_BYTES)
        return IssuedOpaqueToken(
            plaintext=SecretStr(plaintext),
            digest=self.digest(plaintext, purpose=purpose),
        )

    def digest(self, plaintext: str, *, purpose: str) -> str:
        if not purpose or "\x00" in purpose:
            raise ValueError("purpose must be non-empty and must not contain NUL")
        if not plaintext:
            raise ValueError("plaintext token must not be empty")
        payload = purpose.encode("utf-8") + b"\x00" + plaintext.encode("utf-8")
        return hmac.new(self._pepper, payload, hashlib.sha256).hexdigest()

    def matches(self, plaintext: str, expected_digest: str, *, purpose: str) -> bool:
        if len(expected_digest) != hashlib.sha256().digest_size * 2:
            return False
        actual = self.digest(plaintext, purpose=purpose)
        return hmac.compare_digest(actual, expected_digest)
