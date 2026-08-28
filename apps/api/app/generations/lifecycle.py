"""User lifecycle mutations and crash-safe artifact deletion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import AuditContext, append_audit_event
from app.generations.errors import GenerationNotFoundError, GenerationStateConflictError
from app.generations.ports import ArtifactStoragePort
from app.infrastructure.models import GenerationArtifacts, GenerationJobs

_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "expired"})


class GenerationLifecycleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def cancel_accepted(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        job_id: UUID,
        audit_context: AuditContext,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session.begin():
            job = await self._lock_visible_job(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                job_id=job_id,
            )
            if job.status == "cancelled":
                return
            if job.status != "accepted":
                raise GenerationStateConflictError()
            job.status = "cancelled"
            job.completed_at = now
            job.updated_at = now
            job.error_code = None
            job.reconciliation_status = "not_required"
            append_audit_event(
                self._session,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="generation.cancel",
                resource_type="generation_job",
                resource_id=job.id,
                context=audit_context,
                payload={"phase": "accepted"},
            )

    async def soft_delete(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        job_id: UUID,
        audit_context: AuditContext,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session.begin():
            job = await self._lock_visible_job(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                job_id=job_id,
            )
            if job.deleted_at is not None:
                return
            if job.status not in _TERMINAL:
                raise GenerationStateConflictError()
            job.deleted_at = now
            job.updated_at = now
            await self._session.execute(
                update(GenerationArtifacts)
                .where(
                    GenerationArtifacts.tenant_id == tenant_id,
                    GenerationArtifacts.generation_job_id == job.id,
                    GenerationArtifacts.status.in_(("pending", "ready")),
                )
                .values(status="expired", expires_at=now, updated_at=now)
            )
            append_audit_event(
                self._session,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="generation.delete",
                resource_type="generation_job",
                resource_id=job.id,
                context=audit_context,
                payload={"retention": "cleanup_pending"},
            )

    async def _lock_visible_job(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        job_id: UUID,
    ) -> GenerationJobs:
        job = (
            await self._session.execute(
                select(GenerationJobs)
                .where(
                    GenerationJobs.tenant_id == tenant_id,
                    GenerationJobs.actor_user_id == actor_user_id,
                    GenerationJobs.job_id == job_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            raise GenerationNotFoundError()
        return job


@dataclass(frozen=True, slots=True)
class ArtifactDeletionClaim:
    artifact_id: UUID
    tenant_id: UUID
    job_db_id: UUID
    job_id: UUID
    object_key: str


class ArtifactCleanupService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        storage: ArtifactStoragePort,
    ) -> None:
        self._sessions = sessions
        self._storage = storage

    async def run_once(self) -> bool:
        claim = await self._claim()
        if claim is None:
            return False
        try:
            await self._storage.delete_object(
                tenant_id=claim.tenant_id,
                job_id=claim.job_id,
                object_key=claim.object_key,
            )
        except Exception:
            await self._retry(claim)
            raise
        await self._complete(claim)
        return True

    async def _claim(self) -> ArtifactDeletionClaim | None:
        now = datetime.now(UTC)
        stale_delete = now - timedelta(minutes=5)
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    select(GenerationArtifacts, GenerationJobs.job_id)
                    .join(
                        GenerationJobs,
                        (GenerationJobs.tenant_id == GenerationArtifacts.tenant_id)
                        & (GenerationJobs.id == GenerationArtifacts.generation_job_id),
                    )
                    .where(
                        or_(
                            and_(
                                GenerationArtifacts.status == "expired",
                                GenerationArtifacts.expires_at.is_not(None),
                                GenerationArtifacts.expires_at <= now,
                            ),
                            and_(
                                GenerationArtifacts.status == "delete_pending",
                                GenerationArtifacts.updated_at <= stale_delete,
                            ),
                        ),
                    )
                    .order_by(GenerationArtifacts.expires_at, GenerationArtifacts.id)
                    .limit(1)
                    .with_for_update(of=GenerationArtifacts, skip_locked=True)
                )
            ).first()
            if row is None:
                return None
            artifact, public_job_id = row
            artifact.status = "delete_pending"
            artifact.updated_at = now
            return ArtifactDeletionClaim(
                artifact_id=artifact.id,
                tenant_id=artifact.tenant_id,
                job_db_id=artifact.generation_job_id,
                job_id=public_job_id,
                object_key=artifact.object_key,
            )

    async def _complete(self, claim: ArtifactDeletionClaim) -> None:
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(GenerationArtifacts)
                .where(
                    GenerationArtifacts.tenant_id == claim.tenant_id,
                    GenerationArtifacts.id == claim.artifact_id,
                    GenerationArtifacts.status == "delete_pending",
                )
                .values(
                    status="deleted",
                    object_key=f"deleted/{claim.artifact_id}",
                    size_bytes=0,
                    sha256=None,
                    expires_at=now,
                    updated_at=now,
                )
            )
            if _rowcount(result) != 1:
                raise GenerationStateConflictError()

    async def _retry(self, claim: ArtifactDeletionClaim) -> None:
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(GenerationArtifacts)
                .where(
                    GenerationArtifacts.tenant_id == claim.tenant_id,
                    GenerationArtifacts.id == claim.artifact_id,
                    GenerationArtifacts.status == "delete_pending",
                )
                .values(
                    status="expired",
                    expires_at=now + timedelta(minutes=5),
                    updated_at=now,
                )
            )


def _rowcount(result: object) -> int:
    return int(cast(CursorResult[Any], result).rowcount)


__all__ = [
    "ArtifactCleanupService",
    "ArtifactDeletionClaim",
    "GenerationLifecycleService",
]
