"""HTTP boundary for durable, asynchronous generation jobs."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.writer import AuditContext
from app.auth.permissions import require_csrf_permission, require_permission
from app.auth.repository import CurrentAuth
from app.billing.service import SqlAlchemyBillingService
from app.contracts.generations import CreateGenerationRequest, GenerationJobResponse
from app.core.settings import settings
from app.generations.errors import GenerationInfrastructureError, GenerationNotFoundError
from app.generations.lifecycle import GenerationLifecycleService
from app.generations.ports import ArtifactStoragePort
from app.generations.readiness import (
    are_generation_workers_ready,
    is_generation_worker_ready_for_modality,
)
from app.generations.repository import SqlAlchemyGenerationRepository
from app.generations.service import GenerationService
from app.generations.storage import build_artifact_storage
from app.infrastructure.database import get_db_session
from app.infrastructure.models import GenerationArtifacts, GenerationJobs

router = APIRouter(prefix="/api/v1/generations", tags=["generations"])
require_generation_permission = require_permission("generation:use")
require_generation_csrf_permission = require_csrf_permission("generation:use")


async def generation_execution_stack_ready() -> bool:
    return await are_generation_workers_ready()


async def generation_worker_ready_for_request(
    payload: Annotated[CreateGenerationRequest, Body()],
) -> bool:
    return await is_generation_worker_ready_for_modality(payload.modality)


def require_generation_submission_enabled(
    is_execution_stack_ready: Annotated[bool, Depends(generation_worker_ready_for_request)],
) -> None:
    if not settings.generation_submission_enabled or not is_execution_stack_ready:
        raise GenerationInfrastructureError("GENERATION_SUBMISSION_DISABLED")


def get_generation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GenerationService:
    return GenerationService(
        SqlAlchemyGenerationRepository(session, billing=SqlAlchemyBillingService(session))
    )


def get_generation_lifecycle_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GenerationLifecycleService:
    return GenerationLifecycleService(session)


def _audit_context(request: Request) -> AuditContext:
    raw_request_id = getattr(request.state, "request_id", None)
    try:
        request_id = UUID(str(raw_request_id)) if raw_request_id is not None else None
    except ValueError:
        request_id = None
    return AuditContext(
        request_id=request_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@lru_cache(maxsize=1)
def get_generation_artifact_storage() -> ArtifactStoragePort:
    return build_artifact_storage(settings)


@router.get("", response_model=list[GenerationJobResponse])
async def list_generations(
    response: Response,
    auth: Annotated[CurrentAuth, Depends(require_generation_permission)],
    service: Annotated[GenerationService, Depends(get_generation_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[GenerationJobResponse]:
    response.headers["Cache-Control"] = "no-store"
    return await service.list_recent(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        limit=limit,
    )


@router.post(
    "",
    response_model=GenerationJobResponse,
    status_code=202,
    dependencies=[Depends(require_generation_submission_enabled)],
)
async def create_generation(
    payload: CreateGenerationRequest,
    response: Response,
    auth: Annotated[CurrentAuth, Depends(require_generation_csrf_permission)],
    service: Annotated[GenerationService, Depends(get_generation_service)],
) -> GenerationJobResponse:
    accepted = await service.accept(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        request=payload,
    )
    response.headers["Location"] = f"/api/v1/generations/{accepted.record.job_id}"
    response.headers["Cache-Control"] = "no-store"
    return accepted.record.public_response()


@router.get("/{job_id}", response_model=GenerationJobResponse)
async def get_generation(
    job_id: UUID,
    response: Response,
    auth: Annotated[CurrentAuth, Depends(require_generation_permission)],
    service: Annotated[GenerationService, Depends(get_generation_service)],
) -> GenerationJobResponse:
    """Return only the public projection for the authenticated tenant."""

    response.headers["Cache-Control"] = "no-store"
    return await service.get(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        job_id=job_id,
    )


@router.post("/{job_id}/cancel", status_code=204)
async def cancel_generation(
    job_id: UUID,
    request: Request,
    auth: Annotated[CurrentAuth, Depends(require_generation_csrf_permission)],
    service: Annotated[GenerationLifecycleService, Depends(get_generation_lifecycle_service)],
) -> Response:
    await service.cancel_accepted(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        job_id=job_id,
        audit_context=_audit_context(request),
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.delete("/{job_id}", status_code=204)
async def delete_generation(
    job_id: UUID,
    request: Request,
    auth: Annotated[CurrentAuth, Depends(require_generation_csrf_permission)],
    service: Annotated[GenerationLifecycleService, Depends(get_generation_lifecycle_service)],
) -> Response:
    await service.soft_delete(
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        job_id=job_id,
        audit_context=_audit_context(request),
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/{job_id}/artifacts/{artifact_id}")
async def download_generation_artifact(
    job_id: UUID,
    artifact_id: UUID,
    auth: Annotated[CurrentAuth, Depends(require_generation_permission)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ArtifactStoragePort, Depends(get_generation_artifact_storage)],
) -> StreamingResponse:
    """Proxy a ready artifact through the authenticated tenant/job pair."""

    row = (
        await session.execute(
            select(GenerationArtifacts, GenerationJobs)
            .join(
                GenerationJobs,
                and_(
                    GenerationJobs.tenant_id == GenerationArtifacts.tenant_id,
                    GenerationJobs.id == GenerationArtifacts.generation_job_id,
                ),
            )
            .where(
                GenerationArtifacts.tenant_id == auth.tenant_id,
                GenerationArtifacts.id == artifact_id,
                GenerationArtifacts.status == "ready",
                GenerationJobs.tenant_id == auth.tenant_id,
                GenerationJobs.job_id == job_id,
                GenerationJobs.deleted_at.is_(None),
                GenerationJobs.actor_user_id == auth.user_id,
            )
        )
    ).first()
    if row is None:
        raise GenerationNotFoundError()
    artifact, _job = row
    if artifact.storage_provider != storage.storage_provider:
        raise GenerationNotFoundError()
    stream = await storage.open_stream(
        tenant_id=auth.tenant_id,
        job_id=job_id,
        object_key=artifact.object_key,
    )
    return StreamingResponse(
        stream,
        media_type=artifact.mime_type,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="artifact-{artifact_id}"',
            "Content-Length": str(artifact.size_bytes),
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = [
    "cancel_generation",
    "create_generation",
    "delete_generation",
    "download_generation_artifact",
    "generation_execution_stack_ready",
    "generation_worker_ready_for_request",
    "get_generation",
    "get_generation_artifact_storage",
    "get_generation_lifecycle_service",
    "get_generation_service",
    "list_generations",
    "require_generation_submission_enabled",
    "router",
]
