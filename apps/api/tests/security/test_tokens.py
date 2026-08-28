import pytest
from pydantic import SecretStr

from app.security.tokens import (
    SESSION_TOKEN_PEPPER_ENV,
    OpaqueTokenCodec,
    SessionTokenConfigurationError,
)


def test_issued_token_is_high_entropy_and_repr_is_redacted() -> None:
    pepper = "p" * 32
    codec = OpaqueTokenCodec(SecretStr(pepper))

    issued = codec.issue("session")
    plaintext = issued.plaintext.get_secret_value()

    assert len(plaintext) >= 43
    assert len(issued.digest) == 64
    assert plaintext not in repr(issued)
    assert pepper not in repr(codec)
    assert codec.matches(plaintext, issued.digest, purpose="session")


def test_token_digests_are_purpose_separated() -> None:
    codec = OpaqueTokenCodec(SecretStr("p" * 32))
    plaintext = "a-valid-high-entropy-token"

    session_digest = codec.digest(plaintext, purpose="session")
    reset_digest = codec.digest(plaintext, purpose="password-reset")

    assert session_digest != reset_digest
    assert not codec.matches(plaintext, session_digest, purpose="password-reset")


@pytest.mark.parametrize("purpose", ["", "session\x00forged"])
def test_invalid_purpose_is_rejected(purpose: str) -> None:
    codec = OpaqueTokenCodec(SecretStr("p" * 32))

    with pytest.raises(ValueError):
        codec.digest("token", purpose=purpose)


def test_process_environment_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SESSION_TOKEN_PEPPER_ENV, raising=False)

    with pytest.raises(SessionTokenConfigurationError):
        OpaqueTokenCodec.from_process_environment()


def test_short_pepper_is_rejected() -> None:
    with pytest.raises(SessionTokenConfigurationError):
        OpaqueTokenCodec(SecretStr("too-short"))


@pytest.mark.parametrize(
    "value",
    [
        "REPLACE_WITH_32_CHAR_SESSION_TOKEN_PEPPER",
        "session-token-placeholder-with-enough-characters",
    ],
)
def test_placeholder_pepper_is_rejected(value: str) -> None:
    with pytest.raises(SessionTokenConfigurationError):
        OpaqueTokenCodec(SecretStr(value))


def test_malformed_digest_never_matches() -> None:
    codec = OpaqueTokenCodec(SecretStr("p" * 32))

    assert not codec.matches("token", "not-a-sha256-digest", purpose="session")
