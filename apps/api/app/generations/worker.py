"""Durable, fail-closed generation worker execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Self, TypeVar, cast
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.writer import AuditContext, append_audit_event
from app.billing.errors import RESERVATION_EXPIRED, BillingConflict
from app.billing.ports import (
    BillingSettlementPort,
    BillingUsage,
    CaptureResult,
    ReleaseResult,
)
from app.billing.service import SqlAlchemyBillingService
from app.contracts.generations import GenerationModality
from app.generations.errors import GenerationInfrastructureError
from app.generations.executor import DashScopeGenerationExecutor
from app.generations.ports import (
    ArtifactStoragePort,
    GenerationExecutionResult,
    GenerationExecutorPort,
    GenerationHeartbeatPort,
    GenerationUsage,
    ProviderPorts,
    ProviderResolverPort,
)
from app.generations.repository import GenerationRecord, GenerationRepository, OutboxRecord
from app.generations.state import is_terminal
from app.infrastructure.concurrency import (
    ConcurrencySaturated,
    ConcurrencyUnavailable,
    RedisLeaseGuard,
    RedisLeaseSemaphore,
    acquire_deployment_admission,
)
from app.infrastructure.models import BalanceReservations, GenerationJobs, UsageRecords
from app.observability.logging import log_event
from app.observability.metrics import record_worker_outcome
from app.providers.errors import ProviderError

_ResultT = TypeVar("_ResultT")


class SqlAlchemyGenerationBilling(BillingSettlementPort):
    """Use a fresh database session for idempotent capture/release only."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def capture(self, **kwargs: Any) -> CaptureResult:
        async with self._sessions() as session:
            return await SqlAlchemyBillingService(session).capture(**kwargs)

    async def release(self, **kwargs: Any) -> ReleaseResult:
        async with self._sessions() as session:
            return await SqlAlchemyBillingService(session).release(**kwargs)

    async def reconcile_once(self, *, limit: int = 50) -> int:
        if not 1 <= limit <= 500:
            raise ValueError("reconciliation limit must be between 1 and 500")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(
                        BalanceReservations.tenant_id,
                        BalanceReservations.id,
                        GenerationJobs.id,
                        GenerationJobs.status,
                        GenerationJobs.reconciliation_status,
                        UsageRecords.id,
                    )
                    .join(
                        GenerationJobs,
                        and_(
                            GenerationJobs.tenant_id == BalanceReservations.tenant_id,
                            GenerationJobs.id == BalanceReservations.source_id,
                        ),
                    )
                    .outerjoin(
                        UsageRecords,
                        and_(
                            UsageRecords.tenant_id == GenerationJobs.tenant_id,
                            UsageRecords.generation_job_id == GenerationJobs.id,
                        ),
                    )
                    .where(
                        BalanceReservations.source_type == "generation",
                        BalanceReservations.status == "pending",
                        GenerationJobs.status.in_(
                            ("succeeded", "failed", "cancelled", "expired")
                        ),
                    )
                    .order_by(BalanceReservations.created_at)
                    .limit(limit)
                )
            ).all()
        repaired = 0
        for tenant_id, reservation_id, job_db_id, status, reconciliation_status, usage_id in rows:
            if status == "succeeded" and usage_id is None:
                continue
            if status == "succeeded":
                await self._capture_or_release_expired(
                    tenant_id=tenant_id,
                    reservation_id=reservation_id,
                )
            else:
                await self.release(tenant_id=tenant_id, reservation_id=reservation_id)
            if status == "failed" and reconciliation_status == "pending":
                await self._mark_reconciliation_resolved(
                    tenant_id=tenant_id,
                    job_db_id=job_db_id,
                )
            repaired += 1
        return repaired

    async def _mark_reconciliation_resolved(
        self,
        *,
        tenant_id: UUID,
        job_db_id: UUID,
    ) -> None:
        async with self._sessions() as session, session.begin():
            job = (
                await session.execute(
                    select(GenerationJobs)
                    .where(
                        GenerationJobs.tenant_id == tenant_id,
                        GenerationJobs.id == job_db_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if job is None or job.reconciliation_status != "pending":
                return
            job.reconciliation_status = "resolved"
            job.updated_at = datetime.now(UTC)
            append_audit_event(
                session,
                tenant_id=tenant_id,
                actor_user_id=None,
                action="generation.reconciliation.resolved",
                resource_type="generation_job",
                resource_id=job.id,
                context=AuditContext(user_agent="generation-billing-reconciler"),
                payload={"operator_subject": "system:generation-billing-reconciler"},
            )

    async def _capture_or_release_expired(
        self,
        *,
        tenant_id: UUID,
        reservation_id: UUID,
    ) -> None:
        try:
            await self.capture(
                tenant_id=tenant_id,
                reservation_id=reservation_id,
            )
        except BillingConflict as exc:
            if exc.code != RESERVATION_EXPIRED:
                raise
            await self.release(tenant_id=tenant_id, reservation_id=reservation_id)

class SqlAlchemyGenerationHeartbeat(GenerationHeartbeatPort):
    """Touch only a non-terminal claimed job through an independent txn."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        lease_seconds: int = 120,
    ) -> None:
        if not 1 <= lease_seconds <= 3_600:
            raise ValueError("generation heartbeat lease is invalid")
        self._sessions = sessions
        self._lease_seconds = lease_seconds

    async def ensure_live(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        fencing_token: int,
        phase: str,
    ) -> None:
        if not phase or len(phase) > 64:
            raise ValueError("heartbeat phase is invalid")
        if not worker_id.strip() or fencing_token < 1:
            raise ValueError("heartbeat fence is invalid")
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(GenerationJobs)
                .where(
                    GenerationJobs.tenant_id == tenant_id,
                    GenerationJobs.job_id == job_id,
                    GenerationJobs.status.in_(
                        ("reserved", "queued", "submitted", "running", "storing")
                    ),
                    GenerationJobs.claim_owner == worker_id,
                    GenerationJobs.lease_token == lease_token,
                    GenerationJobs.fencing_token == fencing_token,
                    GenerationJobs.lease_expires_at > now,
                )
                .values(
                    updated_at=now,
                    lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise GenerationInfrastructureError("GENERATION_HEARTBEAT_LOST")

    async def reconcile_stalled_once(
        self,
        *,
        stale_seconds: int = 1200,
        limit: int = 50,
    ) -> int:
        if stale_seconds < 60 or not 1 <= limit <= 500:
            raise ValueError("invalid generation reconciliation bounds")
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            jobs = tuple(
                (
                    await session.execute(
                        select(GenerationJobs)
                        .where(
                            GenerationJobs.status.in_(
                                ("reserved", "queued", "submitted", "running", "storing")
                            ),
                            GenerationJobs.lease_expires_at.is_not(None),
                            GenerationJobs.lease_expires_at <= now,
                        )
                        .order_by(GenerationJobs.updated_at, GenerationJobs.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            )
            reconciled = 0
            for job in jobs:
                if job.status in {"reserved", "queued"}:
                    # No chargeable provider call is allowed before submitted.
                    job.status = "failed"
                    job.error_code = "GENERATION_WORKER_STALLED"
                    job.completed_at = now
                    job.updated_at = now
                    job.claim_owner = None
                    job.lease_token = None
                    job.lease_expires_at = None
                    job.reconciliation_status = "not_required"
                    reconciled += 1
                elif job.status in {"submitted", "running", "storing"}:
                    # Any post-submission state may already have reached the
                    # provider or local artifact store.  Move it to the one
                    # explicit non-terminal manual-reconciliation state; do
                    # not turn it into a releasable failed job automatically.
                    job.status = "submitted_unknown"
                    job.error_code = "GENERATION_RECONCILIATION_REQUIRED"
                    job.updated_at = now
                    job.claim_owner = None
                    job.lease_token = None
                    job.lease_expires_at = None
                    job.reconciliation_status = "pending"
                    reconciled += 1
            return reconciled


@dataclass(frozen=True, slots=True)
class WorkerDependencies:
    provider_resolver: ProviderResolverPort | None = None
    artifact_storage: ArtifactStoragePort | None = None
    billing: BillingSettlementPort | None = None
    executor: GenerationExecutorPort | None = None
    heartbeat: GenerationHeartbeatPort | None = None
    # ``billing_factory`` is useful when a host owns its session lifecycle;
    # ``billing_session_factory`` is the production composition path and
    # constructs SqlAlchemyBillingService with a new session per operation.
    billing_factory: Callable[[], BillingSettlementPort] | None = None
    billing_session_factory: async_sessionmaker[AsyncSession] | None = None
    concurrency: RedisLeaseSemaphore | None = None
    concurrency_lease_seconds: float = 120.0
    concurrency_renewal_interval_seconds: float | None = None
    concurrency_retry_delay_seconds: float = 2.0
    worker_id: str = "generation-worker"


class _GenerationDbLeaseGuard:
    def __init__(
        self,
        heartbeat: GenerationHeartbeatPort,
        *,
        job: GenerationRecord,
        worker_id: str,
        lease_seconds: float,
    ) -> None:
        self._heartbeat = heartbeat
        self._job = job
        self._worker_id = worker_id
        self._interval = min(max(lease_seconds / 3, 1.0), 30.0)
        self._stopped = asyncio.Event()
        self._lost = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        self._task = asyncio.create_task(self._renew_loop())
        return self

    async def __aexit__(self, *_: object) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def run(self, operation: Awaitable[_ResultT]) -> _ResultT:
        operation_task = asyncio.ensure_future(operation)
        lost_task = asyncio.create_task(self._lost.wait())
        done, _ = await asyncio.wait(
            (operation_task, lost_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if operation_task in done:
            lost_task.cancel()
            with suppress(asyncio.CancelledError):
                await lost_task
            return await operation_task
        operation_task.cancel()
        with suppress(asyncio.CancelledError):
            await operation_task
        raise GenerationInfrastructureError("GENERATION_LEASE_LOST")

    async def _renew_loop(self) -> None:
        lease_token, fencing_token = _require_job_fence(self._job)
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)
                return
            except TimeoutError:
                pass
            try:
                await self._heartbeat.ensure_live(
                    tenant_id=self._job.tenant_id,
                    job_id=self._job.job_id,
                    worker_id=self._worker_id,
                    lease_token=lease_token,
                    fencing_token=fencing_token,
                    phase="provider_in_flight",
                )
            except Exception:  # noqa: BLE001 - loss must cancel provider processing
                self._lost.set()
                return


class DurableGenerationWorker:
    """Claim accepted jobs once, then execute a charge-safe provider path."""

    def __init__(
        self,
        repository: GenerationRepository,
        dependencies: WorkerDependencies,
    ) -> None:
        if not dependencies.worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if dependencies.concurrency_lease_seconds < 1:
            raise ValueError("concurrency lease must be at least one second")
        if dependencies.concurrency_renewal_interval_seconds is not None and (
            dependencies.concurrency_renewal_interval_seconds <= 0
        ):
            raise ValueError("concurrency renewal interval must be positive")
        if dependencies.concurrency_retry_delay_seconds <= 0:
            raise ValueError("concurrency retry delay must be positive")
        self._repository = repository
        self._dependencies = dependencies

    async def process(self, event: OutboxRecord) -> None:
        """Process an untrusted at-least-once event envelope."""

        self._require_dependencies()
        if event.aggregate_type != "generation_job" or event.event_type != "generation.accepted":
            raise GenerationInfrastructureError("GENERATION_EVENT_INVALID")
        job_id = _event_job_id(event)
        claimed = await self._claim(event.tenant_id, job_id)
        if claimed is None:
            return
        await self._execute_claimed(claimed)

    async def run_once(
        self,
        *,
        tenant_id: UUID | None = None,
        modalities: Collection[GenerationModality] | None = None,
    ) -> bool:
        """Claim and process one accepted job when the repository supports polling."""

        self._require_dependencies()
        claim_next = getattr(self._repository, "claim_next_accepted", None)
        if not callable(claim_next):
            raise GenerationInfrastructureError("GENERATION_WORKER_CLAIM_UNAVAILABLE")
        claim_kwargs: dict[str, object] = {"tenant_id": tenant_id}
        claim_kwargs["worker_id"] = self._dependencies.worker_id
        claim_kwargs["lease_seconds"] = int(self._dependencies.concurrency_lease_seconds)
        if modalities is not None:
            claim_kwargs["modalities"] = modalities
        job = cast(GenerationRecord | None, await claim_next(**claim_kwargs))
        if job is None:
            return False
        await self._execute_claimed(job)
        return True

    def _require_dependencies(self) -> None:
        missing = [
            name
            for name, value in (
                ("provider_resolver", self._dependencies.provider_resolver),
                ("artifact_storage", self._dependencies.artifact_storage),
                ("executor", self._dependencies.executor),
                ("heartbeat", self._dependencies.heartbeat),
                ("concurrency", self._dependencies.concurrency),
            )
            if value is None
        ]
        if (
            self._dependencies.billing is None
            and self._dependencies.billing_factory is None
            and self._dependencies.billing_session_factory is None
        ):
            missing.append("billing")
        if missing:
            raise GenerationInfrastructureError(
                "GENERATION_WORKER_NOT_CONFIGURED",
                details={"missing": ",".join(missing)},
            )

    async def _claim(self, tenant_id: UUID, job_id: UUID) -> GenerationRecord | None:
        return await self._repository.claim_accepted(
            tenant_id=tenant_id,
            job_id=job_id,
            worker_id=self._dependencies.worker_id,
            lease_seconds=int(self._dependencies.concurrency_lease_seconds),
        )

    async def _execute_claimed(self, job: GenerationRecord) -> None:
        if job.status != "reserved" or is_terminal(job.status):
            return
        _require_job_fence(job)
        resolver = self._dependencies.provider_resolver
        storage = self._dependencies.artifact_storage
        executor = self._dependencies.executor
        heartbeat = self._dependencies.heartbeat
        assert resolver is not None
        assert storage is not None
        assert executor is not None
        assert heartbeat is not None

        billing = self._billing_port()
        providers: ProviderPorts | None = None
        if job.billing_reservation_id is None:
            await self._fail(
                job,
                expected="reserved",
                error_code="GENERATION_BILLING_RESERVATION_MISSING",
            )
            record_worker_outcome(worker=_worker_metric_label(job), outcome="failure")
            raise GenerationInfrastructureError("GENERATION_BILLING_RESERVATION_MISSING")
        reservation_id = job.billing_reservation_id
        try:
            # ``queued`` is a durable waiting state, but it owns no Redis
            # permit. Admission is requested only after the job has been
            # claimed and its accepted deployment snapshot is available.
            job = await self._transition(job, expected="reserved", target="queued")
            await heartbeat.ensure_live(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                worker_id=self._dependencies.worker_id,
                lease_token=_require_job_fence(job)[0],
                fencing_token=job.fencing_token,
                phase="before_provider",
            )
            providers = await resolver.resolve(
                deployment_id=job.model_deployment_id,
                tenant_id=job.tenant_id,
            )
            try:
                admission = await self._acquire_admission(job)
            except ConcurrencyUnavailable:
                await self._requeue_after_saturation(job)
                raise
            if admission is None:
                await self._requeue_after_saturation(job)
                raise ConcurrencySaturated(
                    retry_after_seconds=self._dependencies.concurrency_retry_delay_seconds,
                )

            async with admission:
                # This CAS occurs before the first provider call. If the
                # process dies after a chargeable POST, a redelivered event
                # sees ``submitted`` and cannot claim it again.
                job = await self._transition(job, expected="queued", target="submitted")
                async with _GenerationDbLeaseGuard(
                    heartbeat,
                    job=job,
                    worker_id=self._dependencies.worker_id,
                    lease_seconds=self._dependencies.concurrency_lease_seconds,
                ) as database_lease:
                    result = await admission.run(
                        database_lease.run(
                            executor.execute(
                                job=job,
                                providers=providers,
                                artifact_storage=storage,
                                billing=billing,
                                submission_recorder=self._repository,
                            )
                        )
                    )
                if result is None:
                    result = GenerationExecutionResult()
            await heartbeat.ensure_live(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                worker_id=self._dependencies.worker_id,
                lease_token=_require_job_fence(job)[0],
                fencing_token=job.fencing_token,
                phase="after_provider",
            )
            job = await self._transition(
                job,
                expected="submitted",
                target="running",
                provider_request_id=result.provider_request_id,
                provider_task_id=result.provider_task_id,
            )
            job = await self._transition(job, expected="running", target="storing")
            await heartbeat.ensure_live(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                worker_id=self._dependencies.worker_id,
                lease_token=_require_job_fence(job)[0],
                fencing_token=job.fencing_token,
                phase="before_capture",
            )
            job = await self._complete(job, result)
            await billing.capture(
                tenant_id=job.tenant_id,
                reservation_id=reservation_id,
                usage=_billing_usage(result.usage),
            )
            record_worker_outcome(worker=_worker_metric_label(job), outcome="success")
        except (ConcurrencySaturated, ConcurrencyUnavailable):
            # Saturation and an unavailable admission store are retry signals,
            # not Provider failures. The job has already been returned to its
            # accepted state before the exception leaves this method.
            raise
        except Exception as exc:
            # Once ``submitted`` was committed, the outcome of a provider POST
            # is not safely retryable.  Preserve submitted_unknown rather than
            # issuing a second chargeable request on a later delivery.
            submitted_unknown = job.status == "submitted" and _submission_is_uncertain(exc)
            diagnostic_code = (
                exc.code
                if isinstance(exc, (ProviderError, GenerationInfrastructureError))
                else "unexpected_exception"
            )
            log_event(
                "generation.worker.exception",
                level=logging.ERROR,
                worker=_worker_metric_label(job),
                outcome="submitted_unknown" if submitted_unknown else "failure",
                error_code=diagnostic_code,
                status_code=exc.status_code if isinstance(exc, ProviderError) else 503,
            )
            if submitted_unknown:
                await self._fail(job, expected="submitted", error_code="GENERATION_SUBMITTED_UNKNOWN")
                record_worker_outcome(
                    worker=_worker_metric_label(job),
                    outcome="submitted_unknown",
                )
            elif job.status in {"reserved", "queued", "submitted", "running", "storing"}:
                await self._fail(job, expected=job.status, error_code="GENERATION_EXECUTION_FAILED")
                record_worker_outcome(worker=_worker_metric_label(job), outcome="failure")
            elif job.status == "succeeded":
                record_worker_outcome(worker=_worker_metric_label(job), outcome="failure")
            if (
                job.billing_reservation_id is not None
                and not submitted_unknown
                and job.status != "succeeded"
            ):
                await self._release_quietly(
                    billing,
                    tenant_id=job.tenant_id,
                    reservation_id=job.billing_reservation_id,
                )
            raise GenerationInfrastructureError("GENERATION_EXECUTION_FAILED") from exc
        finally:
            if providers is not None:
                await _close_providers(providers)

    async def _acquire_admission(self, job: GenerationRecord) -> RedisLeaseGuard | None:
        semaphore = self._dependencies.concurrency
        if semaphore is None:
            raise GenerationInfrastructureError("GENERATION_CONCURRENCY_NOT_CONFIGURED")
        return await acquire_deployment_admission(
            semaphore,
            tenant_id=job.tenant_id,
            deployment_id=job.model_deployment_id,
            limit=job.concurrency_limit,
            ttl_seconds=self._dependencies.concurrency_lease_seconds,
            renewal_interval_seconds=self._dependencies.concurrency_renewal_interval_seconds,
        )

    async def _requeue_after_saturation(self, job: GenerationRecord) -> None:
        if job.status != "queued":
            return
        try:
            await self._transition(job, expected="queued", target="accepted")
        except Exception as exc:
            raise GenerationInfrastructureError(
                "GENERATION_CONCURRENCY_REQUEUE_FAILED"
            ) from exc

    def _billing_port(self) -> BillingSettlementPort:
        sessions = self._dependencies.billing_session_factory
        if sessions is not None:
            return SqlAlchemyGenerationBilling(sessions)
        factory = self._dependencies.billing_factory
        if factory is not None:
            return _FactoryBilling(factory)
        billing = self._dependencies.billing
        assert billing is not None
        return billing

    async def _transition(
        self,
        job: GenerationRecord,
        *,
        expected: Any,
        target: Any,
        provider_request_id: str | None = None,
        provider_task_id: str | None = None,
    ) -> GenerationRecord:
        transition = self._repository.transition
        lease_token, fencing_token = _require_job_fence(job)
        kwargs: dict[str, Any] = {
            "tenant_id": job.tenant_id,
            "job_id": job.job_id,
            "expected": expected,
            "target": target,
            "lease_token": lease_token,
            "fencing_token": fencing_token,
        }
        if provider_request_id is not None:
            kwargs["provider_request_id"] = provider_request_id
        if provider_task_id is not None:
            kwargs["provider_task_id"] = provider_task_id
        return await transition(**kwargs)

    async def _complete(self, job: GenerationRecord, result: GenerationExecutionResult) -> GenerationRecord:
        complete = getattr(self._repository, "complete", None)
        if not callable(complete):
            raise GenerationInfrastructureError("GENERATION_COMPLETION_UNAVAILABLE")
        kwargs: dict[str, Any] = {
            "tenant_id": job.tenant_id,
            "job_id": job.job_id,
            "expected": "storing",
            "artifacts": result.artifacts,
            "usage": result.usage,
        }
        lease_token, fencing_token = _require_job_fence(job)
        kwargs["lease_token"] = lease_token
        kwargs["fencing_token"] = fencing_token
        if result.provider_request_id is not None:
            kwargs["provider_request_id"] = result.provider_request_id
        if result.provider_task_id is not None:
            kwargs["provider_task_id"] = result.provider_task_id
        return await complete(**kwargs)

    async def _fail(self, job: GenerationRecord, *, expected: Any, error_code: str) -> None:
        transition = self._repository.transition
        try:
            lease_token, fencing_token = _require_job_fence(job)
            await transition(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                expected=expected,
                target=(
                    "submitted_unknown"
                    if error_code == "GENERATION_SUBMITTED_UNKNOWN"
                    else "failed"
                ),
                error_code=error_code,
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
        except Exception:  # noqa: BLE001 - preserve the original processing failure
            return

    async def _release_quietly(
        self,
        billing: BillingSettlementPort,
        *,
        tenant_id: UUID,
        reservation_id: UUID,
    ) -> None:
        try:
            await billing.release(tenant_id=tenant_id, reservation_id=reservation_id)
        except Exception:  # noqa: BLE001 - reconciliation can resolve a failed release
            return


class _FactoryBilling(BillingSettlementPort):
    """Call a host-supplied settlement factory independently per operation."""

    def __init__(self, factory: Callable[[], BillingSettlementPort]) -> None:
        self._factory = factory

    async def capture(self, **kwargs: Any) -> CaptureResult:
        return await self._factory().capture(**kwargs)

    async def release(self, **kwargs: Any) -> ReleaseResult:
        return await self._factory().release(**kwargs)


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


def _billing_usage(usage: GenerationUsage) -> BillingUsage:
    return BillingUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        image_count=usage.image_count,
        video_seconds=usage.video_seconds,
        audio_seconds=usage.audio_seconds,
        character_count=usage.character_count,
        audio_duration_ms=usage.audio_duration_ms,
        video_duration_ms=usage.video_duration_ms,
        storage_bytes=usage.storage_bytes,
        billable_units=usage.billable_units,
    )


def _require_job_fence(job: GenerationRecord) -> tuple[UUID, int]:
    if job.lease_token is None or job.fencing_token < 1:
        raise GenerationInfrastructureError("GENERATION_FENCE_MISSING")
    return job.lease_token, job.fencing_token


def _event_job_id(event: OutboxRecord) -> UUID:
    raw = event.payload.get("job_id")
    try:
        return UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise GenerationInfrastructureError("GENERATION_EVENT_INVALID") from exc


def _submission_is_uncertain(error: Exception) -> bool:
    if isinstance(error, ProviderError):
        # No HTTP status, or a server-side HTTP error, does not give us a
        # definitive outcome.  This covers connect/read timeouts, poll
        # transport errors, submission-unknown errors, and malformed provider
        # responses.
        return error.status_code is None or error.status_code >= 500
    if isinstance(error, GenerationInfrastructureError):
        # Provider task failure is an explicit negative outcome.  Other
        # infrastructure errors after submitted must retain the reservation
        # until an operator/provider reconciliation establishes the outcome.
        return error.code != "GENERATION_PROVIDER_TASK_FAILED"
    # A non-provider exception after the submitted CAS has no trustworthy
    # provider outcome.  Preserve the hold rather than guessing that no POST
    # reached the provider.
    return True


def _worker_metric_label(job: GenerationRecord) -> str:
    return "generation_video" if job.modality == "video" else "generation_media"


__all__ = [
    "DashScopeGenerationExecutor",
    "DurableGenerationWorker",
    "SqlAlchemyGenerationBilling",
    "SqlAlchemyGenerationHeartbeat",
    "WorkerDependencies",
]
