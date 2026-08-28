from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


def test_default_env_file_is_anchored_to_api_package() -> None:
    api_root = Path(__file__).parents[2]
    assert Settings.model_config["env_file"] == api_root / ".env"


def test_checked_in_non_secret_env_example_is_loadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_root = Path(__file__).parents[2]
    for name in (
        "APP_ENVIRONMENT",
        "AUTH_REGISTRATION_ENABLED",
        "AUTH_ALLOWED_ORIGINS",
        "ARTIFACT_STORAGE_BACKEND",
        "ARTIFACT_STORAGE_S3_ENDPOINT_URL",
        "ARTIFACT_STORAGE_S3_BUCKET",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=api_root / ".env.example")

    assert settings.app_environment == "development"
    assert settings.auth_registration_enabled is False
    assert settings.artifact_storage_backend == "s3"
    assert settings.artifact_storage_s3_endpoint_url == "http://127.0.0.1:9000"
    assert settings.artifact_storage_s3_bucket == "mosaic-artifacts"
    assert settings.auth_allowed_origins == (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    )


def test_settings_env_file_override_is_cwd_independent(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / "apps" / "api" / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        "APP_VERSION=9.9.9\nDATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:5432/test\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path / "apps")
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings(_env_file=env_file)

    assert settings.app_version == "9.9.9"
    assert settings.database_url == "postgresql+asyncpg://test:test@127.0.0.1:5432/test"


@pytest.mark.parametrize("invalid_version", ["", "   "])
def test_app_version_rejects_empty_and_whitespace_environment_values(
    invalid_version: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_VERSION", invalid_version)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("environment", "database_url", "secure_cookie"),
    [
        (
            "production",
            "postgresql+asyncpg://mosaic:mosaic@127.0.0.1:5432/mosaic",
            True,
        ),
        (
            "production",
            "postgresql+asyncpg://service:secret@db.internal:5432/mosaic",
            False,
        ),
    ],
)
def test_production_rejects_development_security_defaults(
    environment: str,
    database_url: str,
    secure_cookie: bool,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_environment=environment,
            database_url=database_url,
            session_cookie_secure=secure_cookie,
        )


def test_production_accepts_injected_database_credentials_and_secure_cookie() -> None:
    settings = Settings(
        _env_file=None,
        app_environment="production",
        database_url="postgresql+asyncpg://service:secret@db.internal:5432/mosaic",
        session_cookie_secure=True,
        redis_url="rediss://redis.internal:6380/0",
        rabbitmq_url="amqps://service:secret@rabbit.internal/mosaic",
        auth_allowed_origins=("https://app.example.com",),
        artifact_storage_s3_endpoint_url="https://s3.internal",
        artifact_storage_s3_bucket="mosaic-artifacts",
        artifact_storage_s3_access_key_id="access-key",
        artifact_storage_s3_secret_access_key="secret-key",
        metrics_internal_token="m" * 32,
    )

    assert settings.app_environment == "production"
    assert settings.session_cookie_secure is True


def test_staging_accepts_loopback_services_but_keeps_release_guards() -> None:
    settings = Settings(
        _env_file=None,
        app_environment="staging",
        session_cookie_secure=False,
        artifact_storage_backend="s3",
        artifact_storage_s3_endpoint_url="http://127.0.0.1:9000",
        artifact_storage_s3_bucket="mosaic-artifacts",
        auth_allowed_origins=("http://127.0.0.1:3000",),
        auth_registration_enabled=False,
        metrics_internal_token="m" * 32,
    )
    assert settings.app_environment == "staging"

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_environment="staging",
            artifact_storage_backend="local",
            auth_registration_enabled=False,
        )

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_environment="staging",
            artifact_storage_backend="s3",
            artifact_storage_s3_endpoint_url="http://127.0.0.1:9000",
            artifact_storage_s3_bucket="mosaic-artifacts",
            auth_registration_enabled=True,
        )


def test_release_metrics_require_an_internal_token() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_environment="staging",
            artifact_storage_backend="s3",
            artifact_storage_s3_endpoint_url="http://127.0.0.1:9000",
            artifact_storage_s3_bucket="mosaic-artifacts",
            auth_registration_enabled=False,
            metrics_enabled=True,
            metrics_internal_token=None,
        )


def test_production_rejects_missing_s3_storage() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_environment="production",
            database_url="postgresql+asyncpg://service:secret@db.internal:5432/mosaic",
            session_cookie_secure=True,
            redis_url="rediss://redis.internal:6380/0",
            rabbitmq_url="amqps://service:secret@rabbit.internal/mosaic",
            auth_allowed_origins=("https://app.example.com",),
        )


def test_local_artifact_storage_is_allowed_only_outside_production() -> None:
    settings = Settings(_env_file=None, artifact_storage_backend="local")
    assert settings.artifact_storage_backend == "local"

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_environment="production",
            artifact_storage_backend="local",
            database_url="postgresql+asyncpg://service:secret@db.internal:5432/mosaic",
            session_cookie_secure=True,
            redis_url="rediss://redis.internal:6380/0",
            rabbitmq_url="amqps://service:secret@rabbit.internal/mosaic",
            auth_allowed_origins=("https://app.example.com",),
        )


def test_production_rejects_loopback_auth_origins_even_with_other_safe_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_environment="production",
            database_url="postgresql+asyncpg://service:secret@db.internal:5432/mosaic",
            session_cookie_secure=True,
            rabbitmq_url="amqps://service:secret@rabbit.internal/mosaic",
        )


def test_session_expiry_policy_rejects_invalid_windows() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            session_ttl_seconds=1_800,
            session_idle_ttl_seconds=1_801,
        )

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            session_idle_ttl_seconds=300,
            session_touch_interval_seconds=300,
        )


def test_auth_origins_are_normalized_and_reject_paths() -> None:
    settings = Settings(
        _env_file=None,
        auth_allowed_origins=("HTTPS://APP.EXAMPLE.COM:443/",),
    )
    assert settings.auth_allowed_origins == ("https://app.example.com:443",)

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            auth_allowed_origins=("https://app.example.com/login",),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "sqlite+aiosqlite:///mosaic.db"),
        ("redis_url", "http://127.0.0.1:6379"),
        ("rabbitmq_url", "https://rabbit.internal"),
    ],
)
def test_infrastructure_urls_reject_wrong_protocol(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_unknown_dotenv_keys_fail_closed(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:5432/test\n"
        "MISSPELLED_SECURITY_OPTION=true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)
