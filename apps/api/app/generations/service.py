"""Application service for accepting and reading tenant-scoped jobs."""

from __future__ import annotations

from uuid import UUID

from app.contracts.generations import (
    CreateGenerationRequest,
    GenerationJobResponse,
)
from app.generations.errors import GenerationNotFoundError
from app.generations.repository import (
    AcceptedGeneration,
    GenerationRepository,
    canonical_request_hash,
)


class GenerationService:
    def __init__(self, repository: GenerationRepository) -> None:
        self._repository = repository

    async def accept(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        request: CreateGenerationRequest,
    ) -> AcceptedGeneration:
        return await self._repository.accept(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            request=request,
            request_hash=canonical_request_hash(request),
        )

    async def get(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        job_id: UUID,
    ) -> GenerationJobResponse:
        record = await self._repository.get(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            job_id=job_id,
        )
        if record is None:
            raise GenerationNotFoundError()
        return record.public_response()

    async def list_recent(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        limit: int = 50,
    ) -> list[GenerationJobResponse]:
        records = await self._repository.list_recent(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            limit=limit,
        )
        return [record.public_response() for record in records]

__all__ = ["GenerationService"]
