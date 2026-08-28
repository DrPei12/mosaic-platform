from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.exception_handlers import register_exception_handlers
from app.api.generations import router as generations_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.models import router as models_router
from app.api.usage import router as usage_router
from app.core.settings import settings
from app.infrastructure.database import dispose_engine
from app.infrastructure.redis import dispose_redis
from app.middleware.request_id import RequestIdMiddleware
from app.observability.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    try:
        await dispose_redis()
    finally:
        await dispose_engine()


def create_app() -> FastAPI:
    configure_logging(version=settings.app_version)
    app = FastAPI(title="MOSAIC Platform API", version=settings.app_version, lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(models_router)
    app.include_router(generations_router)
    app.include_router(conversations_router)
    app.include_router(usage_router)
    app.include_router(metrics_router)
    return app


app = create_app()
