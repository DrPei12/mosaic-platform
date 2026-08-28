"""Auditable, idempotent operator resolution for unknown generation outcomes."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import AuditContext, append_audit_event
from app.billing.ports import BillingSettlementPort
from app.billing.service import SqlAlchemyBillingService
from app.generations.errors import GenerationInfrastructureError, GenerationNotFoundError
from app.generations.executor import DashScopeGenerationExecutor
from app.generations.ports import ArtifactStoragePort, ProviderPorts, ProviderResolverPort
from app.generations.repository import GenerationRecord, GenerationRepository
from app.infrastructure.models import GenerationJobs


@dataclass(frozen=True, slots=True)
class PendingGenerationRecovery:
    tenant_id: UUID
    job_id: UUID
    modality: str
    provider_request_id: str | None
    provider_task_id: str | None
    updated_at: datetime


class GenerationRecoveryService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_pending(self, *, limit: int = 50) -> tuple[PendingGenerationRecovery, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("recovery list limit must be between 1 and 500")
        async with self._sessions() as session:
            rows = tuple(
                (
                    await session.execute(
                        select(GenerationJobs)
                        .where(
                            GenerationJobs.reconciliation_status == "pending",
                            GenerationJobs.status.in_(("submitted_unknown", "failed")),
                        )
                        .order_by(GenerationJobs.updated_at, GenerationJobs.id)
                        .limit(limit)
                    )
                ).scalars()
            )
        return tuple(
            PendingGenerationRecovery(
                tenant_id=row.tenant_id,
                job_id=row.job_id,
                modality=row.modality,
                provider_request_id=row.provider_request_id,
                provider_task_id=row.provider_task_id,
                updated_at=_as_utc(row.updated_at),
            )
            for row in rows
        )

    async def resolve_failed(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        operator_subject: str,
        reason: str,
    ) -> None:
        subject = _bounded_text(operator_subject, "operator subject", 200)
        normalized_reason = _bounded_text(reason, "reason", 500)
        now = datetime.now(UTC)
        reservation_id: UUID
        async with self._sessions() as session, session.begin():
            job = (
                await session.execute(
                    select(GenerationJobs)
                    .where(
                        GenerationJobs.tenant_id == tenant_id,
                        GenerationJobs.job_id == job_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if job is None:
                raise GenerationNotFoundError()
            if job.status == "submitted_unknown" and job.reconciliation_status == "pending":
                job.status = "failed"
                job.error_code = "GENERATION_OPERATOR_RESOLVED_FAILED"
                job.completed_at = now
                job.updated_at = now
                job.provider_observed_status = "FAILED"
                job.provider_observed_at = now
                job.claim_owner = None
                job.lease_token = None
                job.lease_expires_at = None
                append_audit_event(
                    session,
                    tenant_id=tenant_id,
                    actor_user_id=None,
                    action="generation.reconciliation.failed_requested",
                    resource_type="generation_job",
                    resource_id=job.id,
                    context=AuditContext(user_agent="operator-cli"),
                    payload={"operator_subject": subject, "reason": normalized_reason},
                )
            elif not (
                job.status == "failed"
                and job.reconciliation_status == "pending"
                and job.provider_observed_status == "FAILED"
            ):
                if (
                    job.status == "failed"
                    and job.reconciliation_status == "resolved"
                    and job.provider_observed_status == "FAILED"
                ):
                    return
                raise GenerationInfrastructureError("GENERATION_RECONCILIATION_CONFLICT")
            if job.billing_reservation_id is None:
                raise GenerationInfrastructureError("GENERATION_BILLING_RESERVATION_MISSING")
            reservation_id = job.billing_reservation_id

        async with self._sessions() as billing_session:
            await SqlAlchemyBillingService(billing_session).release(
                tenant_id=tenant_id,
                reservation_id=reservation_id,
            )

        async with self._sessions() as session, session.begin():
            job = (
                await session.execute(
                    select(GenerationJobs)
                    .where(
                        GenerationJobs.tenant_id == tenant_id,
                        GenerationJobs.job_id == job_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if job is None:
                raise GenerationNotFoundError()
            if job.reconciliation_status == "resolved":
                return
            if job.status != "failed" or job.reconciliation_status != "pending":
                raise GenerationInfrastructureError("GENERATION_RECONCILIATION_CONFLICT")
            job.reconciliation_status = "resolved"
            job.updated_at = datetime.now(UTC)
            append_audit_event(
                session,
                tenant_id=tenant_id,
                actor_user_id=None,
                action="generation.reconciliation.resolved",
                resource_type="generation_job",
                resource_id=job.id,
                context=AuditContext(user_agent="operator-cli"),
                payload={"operator_subject": subject, "outcome": "failed"},
            )


class GenerationVideoRecoveryWorker:
    def __init__(
        self,
        *,
        repository: GenerationRepository,
        provider_resolver: ProviderResolverPort,
        artifact_storage: ArtifactStoragePort,
        billing: BillingSettlementPort,
        recovery: GenerationRecoveryService,
        worker_id: str = "generation-video-reconciler",
        lease_seconds: int = 120,
    ) -> None:
        if not worker_id.strip() or not 1 <= lease_seconds <= 3_600:
            raise ValueError("generation recovery worker configuration is invalid")
        self._repository = repository
        self._provider_resolver = provider_resolver
        self._artifact_storage = artifact_storage
        self._billing = billing
        self._recovery = recovery
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._executor = DashScopeGenerationExecutor()

    async def run_once(self) -> bool:
        job = await self._repository.claim_pending_reconciliation(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if job is None:
            return False
        lease_token, fencing_token = _job_fence(job)
        providers: ProviderPorts | None = None
        try:
            providers = await self._provider_resolver.resolve(
                deployment_id=job.model_deployment_id,
                tenant_id=job.tenant_id,
            )
            try:
                result = await self._executor.recover_video(
                    job=job,
                    providers=providers,
                    artifact_storage=self._artifact_storage,
                )
            except GenerationInfrastructureError as error:
                if error.code != "GENERATION_PROVIDER_TASK_FAILED":
                    raise
                await self._recovery.resolve_failed(
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    operator_subject="system:generation-video-reconciler",
                    reason="provider reported a definitive failed or cancelled task",
                )
                return True
            if result is None:
                await self._repository.release_reconciliation_claim(
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    lease_token=lease_token,
                    fencing_token=fencing_token,
                )
                return True
            job = await self._repository.transition(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                expected="submitted_unknown",
                target="running",
                provider_request_id=result.provider_request_id,
                provider_task_id=result.provider_task_id,
                provider_observed_status="SUCCEEDED",
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
            job = await self._repository.transition(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                expected="running",
                target="storing",
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
            completed = await self._repository.complete(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                expected="storing",
                artifacts=result.artifacts,
                usage=result.usage,
                provider_request_id=result.provider_request_id,
                provider_task_id=result.provider_task_id,
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
            if completed.billing_reservation_id is None:
                raise GenerationInfrastructureError("GENERATION_BILLING_RESERVATION_MISSING")
            await self._billing.capture(
                tenant_id=completed.tenant_id,
                reservation_id=completed.billing_reservation_id,
                usage=None,
            )
            return True
        except Exception:
            with suppress(Exception):
                await self._repository.release_reconciliation_claim(
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    lease_token=lease_token,
                    fencing_token=fencing_token,
                )
            raise
        finally:
            if providers is not None:
                await _close_providers(providers)


def _bounded_text(value: str, label: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} is invalid")
    return normalized


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _job_fence(job: GenerationRecord) -> tuple[UUID, int]:
    if job.lease_token is None or job.fencing_token < 1:
        raise GenerationInfrastructureError("GENERATION_FENCE_MISSING")
    return job.lease_token, job.fencing_token


async def _close_providers(providers: ProviderPorts) -> None:
    seen: set[int] = set()
    for provider in (providers.text, providers.image, providers.video, providers.audio):
        if provider is None or id(provider) in seen:
            continue
        seen.add(id(provider))
        close = getattr(provider, "aclose", None)
        if callable(close):
            with suppress(Exception):
                await close()


__all__ = [
    "GenerationRecoveryService",
    "GenerationVideoRecoveryWorker",
    "PendingGenerationRecovery",
]
