import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_TENANT_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,118}[a-z0-9])?$")


def _normalise_email(value: str) -> str:
    candidate = value.strip().casefold()
    if (
        len(candidate) > 320
        or candidate.count("@") != 1
        or candidate.startswith("@")
        or candidate.endswith("@")
        or "." not in candidate.rsplit("@", 1)[-1]
    ):
        raise ValueError("email is invalid")
    return candidate


def _normalise_slug(value: str) -> str:
    candidate = value.strip().casefold()
    if not _TENANT_SLUG_RE.fullmatch(candidate):
        raise ValueError("tenant slug is invalid")
    return candidate


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=1024)
    tenant_slug: str | None = Field(default=None, min_length=2, max_length=120)

    @field_validator("account")
    @classmethod
    def normalise_account(cls, value: str) -> str:
        return _normalise_email(value)

    @field_validator("tenant_slug")
    @classmethod
    def normalise_tenant_slug(cls, value: str | None) -> str | None:
        return None if value is None else _normalise_slug(value)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)
    tenant_name: str = Field(min_length=1, max_length=200)
    tenant_slug: str = Field(min_length=2, max_length=120)

    @field_validator("email")
    @classmethod
    def normalise_registration_email(cls, value: str) -> str:
        return _normalise_email(value)

    @field_validator("tenant_name")
    @classmethod
    def validate_tenant_name(cls, value: str) -> str:
        candidate = " ".join(value.split())
        if not candidate:
            raise ValueError("tenant name must not be blank")
        return candidate

    @field_validator("tenant_slug")
    @classmethod
    def normalise_registration_slug(cls, value: str) -> str:
        return _normalise_slug(value)


class AuthSessionResponse(BaseModel):
    """Exact response consumed by the current frontend auth adapter."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    authenticated: bool
    password_change_required: bool = Field(serialization_alias="passwordChangeRequired")


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=8, max_length=1024)
    new_password: str = Field(min_length=12, max_length=128)


class UserSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    session_id: str = Field(min_length=1, serialization_alias="sessionId")
    current: bool
    created_at: datetime = Field(serialization_alias="createdAt")
    last_seen_at: datetime = Field(serialization_alias="lastSeenAt")
    expires_at: datetime = Field(serialization_alias="expiresAt")
    ip_address: str | None = Field(default=None, serialization_alias="ipAddress")
    user_agent: str | None = Field(default=None, serialization_alias="userAgent")


class UserSessionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[UserSessionResponse]
