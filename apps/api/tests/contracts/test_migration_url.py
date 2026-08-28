from pathlib import Path

from alembic import command
from alembic.config import Config

import app.core.settings as settings_module


def test_percent_encoded_password_url_renders_offline_migration(
    monkeypatch,
    capsys,
) -> None:
    database_url = "postgresql+asyncpg://mosaic:p%40ss%25word@127.0.0.1:5432/mosaic"
    monkeypatch.setattr(settings_module.settings, "database_url", database_url)
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))

    command.upgrade(config, "head", sql=True)

    assert "Running upgrade  -> 20260820_0001" in capsys.readouterr().out
