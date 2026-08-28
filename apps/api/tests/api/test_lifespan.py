from unittest.mock import AsyncMock

import pytest

import app.main as main_module
from app.main import create_app


@pytest.mark.asyncio
async def test_app_lifespan_disposes_database_engine_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispose_engine = AsyncMock()
    dispose_redis = AsyncMock()
    monkeypatch.setattr(main_module, "dispose_engine", dispose_engine)
    monkeypatch.setattr(main_module, "dispose_redis", dispose_redis)
    app = create_app()

    async with app.router.lifespan_context(app):
        dispose_engine.assert_not_awaited()
        dispose_redis.assert_not_awaited()

    dispose_redis.assert_awaited_once_with()
    dispose_engine.assert_awaited_once_with()
