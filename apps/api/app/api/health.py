from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.contracts.errors import ErrorBody, ErrorResponse
from app.contracts.health import HealthResponse
from app.conversations.readiness import is_chat_worker_ready
from app.core.request_id import current_request_id
from app.core.settings import settings
from app.generations.readiness import (
    is_generation_media_worker_ready,
    is_generation_video_worker_ready,
)
from app.infrastructure.database import probe_database
from app.infrastructure.redis import probe_redis
from app.messaging.rabbitmq import CHAT_ROUTING_KEY, GENERATION_ROUTING_KEY
from app.observability.metrics import record_dependency_ready
from app.outbox.readiness import is_outbox_relay_ready
from app.providers.config import ProviderCredential
from app.providers.errors import ProviderConfigurationError
from app.security.tokens import OpaqueTokenCodec

router = APIRouter(prefix="/api/v1/health", tags=["health"])


async def database_ready() -> bool:
    ready = await probe_database()
    record_dependency_ready(dependency="database", ready=ready)
    return ready


async def redis_ready() -> bool:
    ready = await probe_redis()
    record_dependency_ready(dependency="redis", ready=ready)
    return ready


async def provider_ready() -> bool:
    try:
        ProviderCredential.from_env()
    except ProviderConfigurationError:
        record_dependency_ready(dependency="provider", ready=False)
        return False
    record_dependency_ready(dependency="provider", ready=True)
    return True


async def session_token_codec_ready() -> bool:
    if settings.app_environment == "development":
        record_dependency_ready(dependency="session_token_codec", ready=True)
        return True
    try:
        OpaqueTokenCodec.from_process_environment()
    except Exception:  # noqa: BLE001 - readiness must fail closed
        record_dependency_ready(dependency="session_token_codec", ready=False)
        return False
    record_dependency_ready(dependency="session_token_codec", ready=True)
    return True


async def generation_stack_ready() -> bool:
    media_worker_ready = await is_generation_media_worker_ready()
    video_worker_ready = await is_generation_video_worker_ready()
    relay_ready = await is_outbox_relay_ready(event_type=GENERATION_ROUTING_KEY)
    worker_ready = media_worker_ready and video_worker_ready
    record_dependency_ready(dependency="generation_media_worker", ready=media_worker_ready)
    record_dependency_ready(dependency="generation_video_worker", ready=video_worker_ready)
    record_dependency_ready(dependency="generation_worker", ready=worker_ready)
    record_dependency_ready(dependency="generation_relay", ready=relay_ready)
    ready = settings.generation_submission_enabled and worker_ready and relay_ready
    record_dependency_ready(dependency="generation_stack", ready=ready)
    return ready


async def chat_stack_ready() -> bool:
    worker_ready = await is_chat_worker_ready()
    relay_ready = await is_outbox_relay_ready(event_type=CHAT_ROUTING_KEY)
    record_dependency_ready(dependency="chat_worker", ready=worker_ready)
    record_dependency_ready(dependency="chat_relay", ready=relay_ready)
    ready = settings.chat_submission_enabled and worker_ready and relay_ready
    record_dependency_ready(dependency="chat_stack", ready=ready)
    return ready


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(service="mosaic-api", status="ok", version=settings.app_version)


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": ErrorResponse}},
)
async def ready(
    is_database_ready: Annotated[bool, Depends(database_ready)],
    is_redis_ready: Annotated[bool, Depends(redis_ready)],
    is_provider_ready: Annotated[bool, Depends(provider_ready)],
    is_session_token_codec_ready: Annotated[bool, Depends(session_token_codec_ready)],
    is_generation_stack_ready: Annotated[bool, Depends(generation_stack_ready)],
    is_chat_stack_ready: Annotated[bool, Depends(chat_stack_ready)],
) -> HealthResponse | JSONResponse:
    if (
        is_database_ready
        and is_redis_ready
        and is_provider_ready
        and is_session_token_codec_ready
        and is_generation_stack_ready
        and is_chat_stack_ready
    ):
        record_dependency_ready(dependency="api", ready=True)
        return HealthResponse(service="mosaic-api", status="ready", version=settings.app_version)

    record_dependency_ready(dependency="api", ready=False)
    body = ErrorResponse(
        error=ErrorBody(
            code="SERVICE_DEPENDENCY_NOT_READY",
            message="服务尚未准备好",
            request_id=current_request_id(),
            retryable=True,
        ),
    )
    return JSONResponse(status_code=503, content=body.model_dump())
