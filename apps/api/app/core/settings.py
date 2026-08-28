import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_version: str = Field(default="0.1.0", min_length=1)
    app_environment: Literal["development", "test", "staging", "production"] = "development"
    metrics_enabled: bool = True
    metrics_internal_token: SecretStr | None = None
    metrics_server_enabled: bool = False
    metrics_bind_host: str = "127.0.0.1"
    metrics_port: int = Field(default=9090, ge=1, le=65_535)
    database_url: str = "postgresql+asyncpg://mosaic:mosaic@127.0.0.1:5432/mosaic"
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=200)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    redis_url: str = "redis://127.0.0.1:6379/0"
    rabbitmq_url: SecretStr = SecretStr("amqp://mosaic:mosaic@127.0.0.1:5672/")
    rabbitmq_exchange: str = Field(
        default="mosaic.events",
        pattern=r"^[a-z][a-z0-9._-]{2,127}$",
    )
    rabbitmq_chat_queue: str = Field(
        default="mosaic.chat.inference",
        pattern=r"^[a-z][a-z0-9._-]{2,127}$",
    )
    rabbitmq_generation_queue: str = Field(
        default="mosaic.generation.execute",
        pattern=r"^[a-z][a-z0-9._-]{2,127}$",
    )
    rabbitmq_video_generation_queue: str = Field(
        default="mosaic.generation.video.execute",
        pattern=r"^[a-z][a-z0-9._-]{2,127}$",
    )
    rabbitmq_publish_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    concurrency_lease_seconds: float = Field(default=120.0, ge=1, le=3600)
    concurrency_renewal_interval_seconds: float | None = Field(default=None, gt=0, le=120)
    concurrency_saturated_retry_delay_seconds: float = Field(default=2.0, gt=0, le=60)
    chat_stream_max_duration_seconds: float = Field(default=300.0, ge=1, le=3600)
    chat_stream_replay_fallback_seconds: float = Field(default=5.0, gt=0, le=5)
    chat_stream_tenant_limit: int = Field(default=100, ge=1, le=100_000)
    chat_stream_global_limit: int = Field(default=1_000, ge=1, le=1_000_000)
    chat_stream_lease_seconds: float = Field(default=30.0, ge=1, le=3600)
    chat_stream_renewal_interval_seconds: float | None = Field(default=None, gt=0, le=120)
    session_cookie_name: str = Field(
        default="mosaic_session",
        pattern=r"^[A-Za-z][A-Za-z0-9_-]{2,63}$",
    )
    session_cookie_secure: bool = True
    session_ttl_seconds: int = Field(default=28_800, ge=900, le=86_400)
    session_idle_ttl_seconds: int = Field(default=1_800, ge=300, le=28_800)
    session_touch_interval_seconds: int = Field(default=300, ge=30, le=3_600)
    password_hash_time_cost: int = Field(default=3, ge=1, le=10)
    password_hash_memory_cost_kib: int = Field(default=65_536, ge=16_384, le=1_048_576)
    password_hash_parallelism: int = Field(default=4, ge=1, le=8)
    password_hash_hash_len: int = Field(default=32, ge=16, le=128)
    password_hash_salt_len: int = Field(default=16, ge=16, le=64)
    auth_max_failed_login_attempts: int = Field(default=5, ge=1, le=20)
    auth_lockout_seconds: int = Field(default=900, ge=30, le=86_400)
    auth_login_rate_limit: int = Field(default=20, ge=1, le=1_000)
    auth_login_rate_window_seconds: int = Field(default=60, ge=1, le=3_600)
    auth_registration_enabled: bool = False
    generation_submission_enabled: bool = False
    chat_submission_enabled: bool = False
    # S3 is the secure default.  LocalArtifactStorage is available only when
    # development or test explicitly selects it.
    artifact_storage_backend: Literal["s3", "local"] = "s3"
    artifact_storage_s3_endpoint_url: str | None = None
    artifact_storage_s3_bucket: str | None = None
    artifact_storage_s3_region: str = Field(
        default="us-east-1",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$",
    )
    artifact_storage_s3_access_key_id: SecretStr | None = None
    artifact_storage_s3_secret_access_key: SecretStr | None = None
    artifact_storage_s3_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    artifact_storage_max_bytes: int = Field(default=200 * 1024 * 1024, ge=1, le=2**31)
    artifact_storage_provider_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    artifact_storage_provider_allowed_hosts: tuple[str, ...] = ("assets.aliyuncs.com",)
    artifact_storage_provider_trust_env: bool = False
    auth_allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    )

    @field_validator("app_version")
    @classmethod
    def validate_app_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("app_version must not be blank")
        return value

    @field_validator("metrics_bind_host")
    @classmethod
    def validate_metrics_bind_host(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("metrics_bind_host must not be blank")
        return normalized

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use the postgresql+asyncpg driver")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must use redis:// or rediss://")
        return value

    @field_validator("rabbitmq_url")
    @classmethod
    def validate_rabbitmq_url(cls, value: SecretStr) -> SecretStr:
        parsed = urlsplit(value.get_secret_value())
        if parsed.scheme not in {"amqp", "amqps"} or not parsed.hostname:
            raise ValueError("rabbitmq_url must use amqp:// or amqps://")
        return value

    @field_validator("artifact_storage_s3_endpoint_url")
    @classmethod
    def validate_artifact_storage_s3_endpoint_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalised = value.strip().rstrip("/")
        parsed = urlsplit(normalised)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("artifact_storage_s3_endpoint_url must be a bare HTTP(S) endpoint")
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise ValueError("artifact_storage_s3_endpoint_url contains an invalid port") from exc
        if parsed_port is not None and not 0 <= parsed_port <= 65_535:
            raise ValueError("artifact_storage_s3_endpoint_url contains an invalid port")
        return parsed._replace(
            scheme=parsed.scheme.lower(),
            path="",
            query="",
            fragment="",
        ).geturl().rstrip("/")

    @field_validator("artifact_storage_s3_bucket")
    @classmethod
    def validate_artifact_storage_s3_bucket(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalised = value.strip().lower()
        if re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{1,61}[a-z0-9])?", normalised) is None:
            raise ValueError("artifact_storage_s3_bucket must be a valid bucket name")
        return normalised

    @field_validator("artifact_storage_provider_allowed_hosts")
    @classmethod
    def validate_artifact_storage_provider_allowed_hosts(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not values:
            raise ValueError("artifact_storage_provider_allowed_hosts must not be empty")
        normalised: list[str] = []
        for value in values:
            host = value.strip().lower().rstrip(".")
            if (
                len(host) > 253
                or re.fullmatch(
                    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+",
                    host,
                )
                is None
            ):
                raise ValueError(
                    "artifact_storage_provider_allowed_hosts must contain exact hostnames"
                )
            normalised.append(host)
        return tuple(dict.fromkeys(normalised))

    @field_validator("auth_allowed_origins")
    @classmethod
    def validate_auth_allowed_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalised: list[str] = []
        for raw_value in values:
            parsed = urlsplit(raw_value.strip())
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
                or parsed.hostname is None
            ):
                raise ValueError("auth_allowed_origins must contain absolute HTTP(S) origins")
            try:
                port = parsed.port
            except ValueError as exc:
                raise ValueError("auth_allowed_origins contains an invalid port") from exc
            host = parsed.hostname.lower()
            host_for_authority = f"[{host}]" if ":" in host else host
            authority = f"{host_for_authority}:{port}" if port is not None else host_for_authority
            normalised.append(f"{parsed.scheme.lower()}://{authority}")
        return tuple(dict.fromkeys(normalised))

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        if self.session_idle_ttl_seconds > self.session_ttl_seconds:
            raise ValueError("session idle expiry must not exceed absolute expiry")
        if self.session_touch_interval_seconds >= self.session_idle_ttl_seconds:
            raise ValueError("session touch interval must be shorter than idle expiry")
        if self.app_environment not in {"staging", "production"}:
            return self
        if self.auth_registration_enabled:
            raise ValueError("release environments must keep public registration disabled")
        if self.metrics_enabled and (
            self.metrics_internal_token is None
            or len(self.metrics_internal_token.get_secret_value()) < 32
        ):
            raise ValueError("release metrics require an internal token of at least 32 characters")
        if self.artifact_storage_backend != "s3":
            raise ValueError("release environments require S3-compatible artifact storage")
        if not self.artifact_storage_s3_endpoint_url or not self.artifact_storage_s3_bucket:
            raise ValueError("release environments require an S3 endpoint and bucket")
        has_access_key = bool(
            self.artifact_storage_s3_access_key_id
            and self.artifact_storage_s3_access_key_id.get_secret_value().strip()
        )
        has_secret_key = bool(
            self.artifact_storage_s3_secret_access_key
            and self.artifact_storage_s3_secret_access_key.get_secret_value().strip()
        )
        if has_access_key != has_secret_key:
            raise ValueError("artifact storage credentials must be supplied as a pair")
        if not self.auth_allowed_origins or any(origin == "*" for origin in self.auth_allowed_origins):
            raise ValueError("release environments require explicit auth allowed origins")
        if self.app_environment == "staging":
            return self
        if urlsplit(self.artifact_storage_s3_endpoint_url).scheme != "https":
            raise ValueError("production artifact storage requires HTTPS")
        if "mosaic:mosaic@" in self.database_url:
            raise ValueError("production must not use the development database credentials")
        if not self.session_cookie_secure:
            raise ValueError("production requires secure session cookies")
        rabbitmq_url = self.rabbitmq_url.get_secret_value()
        if (
            not rabbitmq_url.startswith("amqps://")
            or "guest:guest@" in rabbitmq_url
            or "mosaic:mosaic@" in rabbitmq_url
        ):
            raise ValueError("production requires non-default RabbitMQ credentials over TLS")
        blocked_hosts = {"localhost", "127.0.0.1", "::1"}
        if any(urlsplit(origin).hostname in blocked_hosts for origin in self.auth_allowed_origins):
            raise ValueError("production auth origins must not use local hosts")
        return self

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=API_ENV_FILE,
        env_file_encoding="utf-8",
        extra="forbid",
    )


settings = Settings()
