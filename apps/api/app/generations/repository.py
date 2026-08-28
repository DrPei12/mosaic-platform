"""Ports and PostgreSQL repositories for generation jobs.

The repository is the transaction boundary for acceptance.  A job row,
idempotency record, and outbox event are committed together; no background
task is started from an HTTP request.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.ports import BillingAcceptancePort, BillingUsage, PriceSnapshot
from app.billing.pricing import charge_for_usage, pricing_version
from app.billing.service import SqlAlchemyBillingService
from app.catalog.repository import resolve_accepted_decision
from app.contracts.generations import (
    CreateGenerationRequest,
    GenerationArtifactResponse,
    GenerationJobResponse,
    GenerationModality,
    GenerationStatus,
)
from app.generations.errors import (
    GenerationInfrastructureError,
    GenerationNotFoundError,
    GenerationStateConflictError,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    ModelUnavailableError,
)
from app.generations.ports import GenerationArtifactInput, GenerationUsage
from app.generations.state import assert_transition
from app.generations.voice_resources import (
    VoiceResourceUnavailable,
    resolve_audio_voice_binding,
)
from app.infrastructure.models import (
    GenerationArtifacts,
    GenerationJobs,
    IdempotencyRecords,
    InboxEvents,
    ModelDeployments,
    OutboxEvents,
    PriceVersions,
    ProductModels,
    ProviderEndpoints,
    TenantModelEntitlements,
    UsageRecords,
)

_ERROR_CODE_RE = re.compile(r"^[A-Z0-9_]{1,120}$")
_SAFE_OUTBOX_ERROR_KEYS = frozenset({"code", "phase", "retryable"})


def canonical_request_hash(request: CreateGenerationRequest) -> str:
    """Hash the normalized public payload, never a caller-provided raw body."""

    payload = request.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DeploymentRoute:
    """Internal routing snapshot; never serialize this to a public response."""

    product_model_db_id: uuid.UUID
    product_model_id: str
    modality: GenerationModality
    task_type: str
    deployment_id: uuid.UUID
    endpoint_id: uuid.UUID
    provider_name: str
    protocol: str
    base_url: str
    provider_model_id: str
    concurrency_limit: int
    endpoint_key: str
    endpoint_config: Mapping[str, Any]
    deployment_config: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PublicArtifact:
    artifact_id: uuid.UUID
    kind: str
    status: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    db_id: uuid.UUID
    job_id: uuid.UUID
    tenant_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    product_model_id: str
    modality: GenerationModality
    status: GenerationStatus
    request_payload: Mapping[str, Any] = field(repr=False)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    error_code: str | None
    model_deployment_id: uuid.UUID
    # Limit loaded with the accepted route and carried into the worker record;
    # runtime admission does not fall back to a process-global default.
    concurrency_limit: int = 1
    billing_reservation_id: uuid.UUID | None = field(default=None, repr=False)
    claim_owner: str | None = field(default=None, repr=False)
    lease_token: uuid.UUID | None = field(default=None, repr=False)
    lease_expires_at: datetime | None = field(default=None, repr=False)
    fencing_token: int = field(default=0, repr=False)
    reconciliation_status: str = "not_required"
    provider_request_id: str | None = field(default=None, repr=False)
    provider_task_id: str | None = field(default=None, repr=False)
    artifacts: tuple[PublicArtifact, ...] = ()

    def public_response(self) -> GenerationJobResponse:
        return GenerationJobResponse(
            job_id=str(self.job_id),
            product_model_id=self.product_model_id,
            modality=self.modality,
            status=self.status,
            created_at=self.created_at,
            updated_at=self.updated_at,
            completed_at=self.completed_at,
            error_code=self.error_code,
            reconciliation_pending=(
                self.status == "submitted_unknown" and self.reconciliation_status == "pending"
            ),
            artifacts=[
                GenerationArtifactResponse(
                    artifact_id=str(artifact.artifact_id),
                    kind=cast(Literal["input", "output", "thumbnail", "preview"], artifact.kind),
                    status=cast(Literal["pending", "ready", "expired", "deleted"], artifact.status),
                    mime_type=artifact.mime_type,
                    size_bytes=artifact.size_bytes,
                )
                for artifact in self.artifacts
            ],
        )


@dataclass(frozen=True, slots=True)
class AcceptedGeneration:
    record: GenerationRecord
    replayed: bool


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    event_id: uuid.UUID
    tenant_id: uuid.UUID
    aggregate_type: str
    aggregate_id: uuid.UUID
    event_type: str
    aggregate_version: int
    payload: Mapping[str, Any]
    attempts: int


class GenerationRepository(Protocol):
    async def accept(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        request: CreateGenerationRequest,
        request_hash: str,
    ) -> AcceptedGeneration: ...

    async def get(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> GenerationRecord | None: ...

    async def list_recent(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        limit: int = 50,
    ) -> Sequence[GenerationRecord]: ...

    async def claim_accepted(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        lease_seconds: int,
    ) -> GenerationRecord | None: ...

    async def claim_next_accepted(
        self,
        *,
        tenant_id: uuid.UUID | None = None,
        modalities: Collection[GenerationModality] | None = None,
        worker_id: str,
        lease_seconds: int,
    ) -> GenerationRecord | None: ...

    async def transition(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        expected: GenerationStatus,
        target: GenerationStatus,
        error_code: str | None = None,
        provider_request_id: str | None = None,
        provider_task_id: str | None = None,
        provider_observed_status: str | None = None,
        lease_token: uuid.UUID,
        fencing_token: int,
    ) -> GenerationRecord: ...

    async def renew_lease(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        lease_token: uuid.UUID,
        fencing_token: int,
        lease_seconds: int,
    ) -> GenerationRecord: ...

    async def claim_pending_reconciliation(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> GenerationRecord | None: ...

    async def release_reconciliation_claim(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        fencing_token: int,
    ) -> None: ...

    async def record_provider_task(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        provider_task_id: str,
        lease_token: uuid.UUID,
        fencing_token: int,
    ) -> None: ...

    async def record_provider_request(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        provider_request_id: str,
        lease_token: uuid.UUID,
        fencing_token: int,
    ) -> None: ...

    async def complete(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        expected: GenerationStatus,
        artifacts: Sequence[GenerationArtifactInput],
        usage: GenerationUsage,
        provider_request_id: str | None = None,
        provider_task_id: str | None = None,
        lease_token: uuid.UUID,
        fencing_token: int,
    ) -> GenerationRecord: ...

    async def record_inbox_event(
        self,
        *,
        tenant_id: uuid.UUID,
        provider_name: str,
        event_key: str,
        event_type: str,
        normalized_payload: Mapping[str, object],
    ) -> bool: ...

    async def claim_outbox(
        self,
        *,
        limit: int = 50,
        tenant_id: uuid.UUID | None = None,
        lease_seconds: int = 60,
    ) -> Sequence[OutboxRecord]: ...

    async def mark_outbox_published(
        self,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        aggregate_version: int,
    ) -> bool: ...

    async def mark_outbox_failed(
        self,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        aggregate_version: int,
        details: Mapping[str, Any],
    ) -> bool: ...


class RouteUnavailable(RuntimeError):
    """Internal marker for a missing entitlement or active deployment."""


class SqlAlchemyGenerationRepository:
    """PostgreSQL implementation with explicit transaction/CAS boundaries."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        billing: BillingAcceptancePort | None = None,
    ) -> None:
        self._session = session
        self._billing = billing or SqlAlchemyBillingService(session)

    def _route_query(
        self, *, tenant_id: uuid.UUID, request: CreateGenerationRequest
    ) -> Select[Any]:
        return (
            select(ProductModels, TenantModelEntitlements, ModelDeployments, ProviderEndpoints)
            .join(
                TenantModelEntitlements,
                and_(
                    TenantModelEntitlements.product_model_id == ProductModels.id,
                    TenantModelEntitlements.tenant_id == tenant_id,
                    TenantModelEntitlements.enabled.is_(True),
                ),
            )
            .join(
                ModelDeployments,
                ModelDeployments.product_model_id == ProductModels.id,
            )
            .join(
                ProviderEndpoints,
                ProviderEndpoints.id == ModelDeployments.provider_endpoint_id,
            )
            .where(
                ProductModels.model_key == request.product_model_id,
                ProductModels.modality == request.modality,
                ProductModels.status == "active",
                ModelDeployments.status == "active",
                ProviderEndpoints.status == "active",
            )
            .order_by(ModelDeployments.priority, ModelDeployments.created_at)
        )

    async def _resolve_route(
        self, *, tenant_id: uuid.UUID, request: CreateGenerationRequest
    ) -> DeploymentRoute:
        rows = (
            await self._session.execute(
                self._route_query(tenant_id=tenant_id, request=request)
            )
        ).all()
        for product, entitlement, deployment, endpoint in rows:
            capabilities = dict(product.capabilities or {})
            if capabilities.get("execution_policy") == "unsupported":
                continue
            try:
                resolve_audio_voice_binding(
                    provider_model_id=deployment.provider_model_id,
                    routing_config=dict(deployment.routing_config or {}),
                    entitlement_config=dict(entitlement.config or {}),
                )
            except VoiceResourceUnavailable:
                # A lower-priority active route may have a valid tenant-bound
                # resource.  Admission and catalog availability therefore use
                # the same "any usable active route" rule.
                continue
            return DeploymentRoute(
                product_model_db_id=product.id,
                product_model_id=product.model_key,
                modality=cast(GenerationModality, product.modality),
                task_type=product.task_type,
                deployment_id=deployment.id,
                endpoint_id=endpoint.id,
                provider_name=endpoint.provider_name,
                protocol=endpoint.protocol,
                base_url=endpoint.base_url,
                provider_model_id=deployment.provider_model_id,
                concurrency_limit=int(deployment.concurrency_limit),
                endpoint_key=endpoint.endpoint_key,
                endpoint_config=dict(endpoint.config or {}),
                deployment_config=dict(deployment.routing_config or {}),
            )
        raise RouteUnavailable

    async def accept(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        request: CreateGenerationRequest,
        request_hash: str,
    ) -> AcceptedGeneration:
        """Atomically accept a request, or replay its prior idempotent job."""

        async with self._session.begin():
            operation = "generation.create"
            idempotency_id = uuid.uuid4()
            inserted = await self._session.execute(
                pg_insert(IdempotencyRecords)
                .values(
                    id=idempotency_id,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    operation=operation,
                    key=request.client_request_id,
                    request_hash=request_hash,
                    status="processing",
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        IdempotencyRecords.tenant_id,
                        IdempotencyRecords.actor_user_id,
                        IdempotencyRecords.operation,
                        IdempotencyRecords.key,
                    ]
                )
                .returning(IdempotencyRecords.id)
            )
            inserted_id = inserted.scalar_one_or_none()

            if inserted_id is None:
                existing = (
                    await self._session.execute(
                        select(IdempotencyRecords)
                        .where(
                            IdempotencyRecords.tenant_id == tenant_id,
                            IdempotencyRecords.actor_user_id == actor_user_id,
                            IdempotencyRecords.operation == operation,
                            IdempotencyRecords.key == request.client_request_id,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if existing is None:
                    # A concurrent transaction can only make this possible if
                    # the database itself is unavailable/inconsistent.
                    raise GenerationInfrastructureError("GENERATION_PERSISTENCE_UNAVAILABLE")
                if existing.request_hash != request_hash:
                    raise IdempotencyConflictError()
                if existing.resource_id is None:
                    raise IdempotencyInProgressError()
                record = await self._get_by_db_id(
                    tenant_id=tenant_id,
                    db_id=existing.resource_id,
                )
                if record is None:
                    raise GenerationInfrastructureError("GENERATION_PERSISTENCE_UNAVAILABLE")
                return AcceptedGeneration(record=record, replayed=True)

            try:
                route = await self._resolve_route(tenant_id=tenant_id, request=request)
            except RouteUnavailable as exc:
                raise ModelUnavailableError() from exc

            now = datetime.now(UTC)
            db_id = uuid.uuid4()
            job_id = uuid.uuid4()
            request_payload = request.model_dump(mode="json", exclude_none=True)
            decision = await resolve_accepted_decision(
                self._session,
                product_model_id=route.product_model_db_id,
                model_deployment_id=route.deployment_id,
                now=now,
            )
            if decision is None:
                raise ModelUnavailableError()
            job = GenerationJobs(
                id=db_id,
                job_id=job_id,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                model_deployment_id=route.deployment_id,
                modality=request.modality,
                status="accepted",
                request_hash=request_hash,
                request_payload=request_payload,
                created_at=now,
                updated_at=now,
            )
            job.accepted_model_revision_id = decision.model_revision_id
            job.accepted_model_deployment_id = decision.model_deployment_id
            job.accepted_routing_policy_id = decision.routing_policy_id
            job.accepted_price_version_id = decision.price_version_id
            job.accepted_capability_schema_version = decision.capability_schema_version
            job.accepted_capability_schema_hash = decision.capability_schema_hash
            job.accepted_capability_schema = dict(decision.capability_schema)
            job.accepted_input_snapshot = dict(request_payload)
            self._session.add(job)
            await self._session.flush()
            reservation = await self._billing.reserve_in_transaction(
                tenant_id=tenant_id,
                source_type="generation",
                source_id=job.id,
                price=decision.price,
                expires_at=now + timedelta(minutes=15),
            )
            job.billing_reservation_id = reservation.reservation_id
            await self._session.flush()
            self._session.add(
                OutboxEvents(
                    tenant_id=tenant_id,
                    aggregate_type="generation_job",
                    aggregate_id=db_id,
                    event_type="generation.accepted",
                    aggregate_version=1,
                    payload={
                        "job_id": str(job_id),
                        "modality": request.modality,
                        "product_model_id": request.product_model_id,
                        "reservation_id": str(reservation.reservation_id),
                    },
                    status="pending",
                    attempts=0,
                )
            )
            await self._session.flush()
            # Updating the reservation FK applies TimestampMixin.onupdate at
            # the database. SQLAlchemy expires that server-generated value;
            # refresh inside the active async transaction so response mapping
            # never attempts an implicit lazy load outside greenlet_spawn.
            await self._session.refresh(job)

            response = _record_from_job(
                job,
                route.product_model_id,
                (),
                concurrency_limit=route.concurrency_limit,
            )
            response_body = response.public_response().model_dump(mode="json")
            await self._session.execute(
                update(IdempotencyRecords)
                .where(IdempotencyRecords.id == idempotency_id)
                .values(
                    status="completed",
                    response_status=202,
                    response_body=response_body,
                    resource_type="generation_job",
                    resource_id=db_id,
                )
            )
            return AcceptedGeneration(record=response, replayed=False)

    async def get(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> GenerationRecord | None:
        async with self._session.begin():
            row = (
                await self._session.execute(
                    self._job_query().where(
                        GenerationJobs.tenant_id == tenant_id,
                        GenerationJobs.actor_user_id == actor_user_id,
                        GenerationJobs.job_id == job_id,
                        GenerationJobs.deleted_at.is_(None),
                    )
                )
            ).first()
            return await self._materialize(row, tenant_id=tenant_id) if row else None

    async def list_recent(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        limit: int = 50,
    ) -> Sequence[GenerationRecord]:
        if not 1 <= limit <= 100:
            raise ValueError("generation list limit must be between 1 and 100")
        async with self._session.begin():
            rows = (
                await self._session.execute(
                    self._job_query()
                    .where(
                        GenerationJobs.tenant_id == tenant_id,
                        GenerationJobs.deleted_at.is_(None),
                        GenerationJobs.actor_user_id == actor_user_id,
                    )
                    .order_by(GenerationJobs.created_at.desc(), GenerationJobs.id.desc())
                    .limit(limit)
                )
            ).all()
            if not rows:
                return ()

            job_ids = tuple(job.id for job, _deployment, _product in rows)
            artifact_rows = tuple(
                (
                    await self._session.execute(
                        select(GenerationArtifacts)
                        .where(
                            GenerationArtifacts.tenant_id == tenant_id,
                            GenerationArtifacts.generation_job_id.in_(job_ids),
                        )
                        .order_by(
                            GenerationArtifacts.generation_job_id,
                            GenerationArtifacts.id,
                        )
                    )
                ).scalars()
            )
            artifacts_by_job: dict[uuid.UUID, list[PublicArtifact]] = {}
            for artifact in artifact_rows:
                artifacts_by_job.setdefault(artifact.generation_job_id, []).append(
                    _public_artifact(artifact)
                )
            return tuple(
                _record_from_job(
                    job,
                    product.model_key,
                    tuple(artifacts_by_job.get(job.id, ())),
                )
                for job, _deployment, product in rows
            )

    async def claim_accepted(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        lease_seconds: int,
    ) -> GenerationRecord | None:
        """Claim one accepted job with a row lock and a compare-and-set.

        Queue deliveries are at-least-once.  The lock prevents two workers
        from entering the same claim at once; the status predicate makes the
        transition safe even when a stale delivery races with a newer worker.
        A job is never claimed again after it has reached ``reserved`` (or any
        later state), so a chargeable provider POST cannot be retried by this
        path.
        """

        _validate_claim_input(worker_id, lease_seconds)
        now = datetime.now(UTC)
        async with self._session.begin():
            row = (
                await self._session.execute(
                    self._job_query()
                    .where(
                        GenerationJobs.tenant_id == tenant_id,
                        GenerationJobs.job_id == job_id,
                        GenerationJobs.status == "accepted",
                        GenerationJobs.lease_token.is_(None),
                    )
                    .with_for_update(of=GenerationJobs, skip_locked=True)
                )
            ).first()
            if row is None:
                return None
            job, _deployment, _product = row
            result = await self._session.execute(
                update(GenerationJobs)
                .where(
                    GenerationJobs.tenant_id == tenant_id,
                    GenerationJobs.job_id == job_id,
                    GenerationJobs.status == "accepted",
                    GenerationJobs.lease_token.is_(None),
                )
                .values(
                    status="reserved",
                    started_at=job.started_at or now,
                    claim_owner=worker_id,
                    lease_token=uuid.uuid4(),
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    fencing_token=int(job.fencing_token) + 1,
                    updated_at=now,
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                return None
            return await self._get_by_job_id(tenant_id=tenant_id, job_id=job_id)

    async def claim_next_accepted(
        self,
        *,
        tenant_id: uuid.UUID | None = None,
        modalities: Collection[GenerationModality] | None = None,
        worker_id: str,
        lease_seconds: int,
    ) -> GenerationRecord | None:
        """Poll one accepted job with the same lock/CAS claim semantics."""

        _validate_claim_input(worker_id, lease_seconds)
        now = datetime.now(UTC)
        async with self._session.begin():
            predicates: list[Any] = [
                GenerationJobs.status == "accepted",
                GenerationJobs.lease_token.is_(None),
            ]
            if tenant_id is not None:
                predicates.append(GenerationJobs.tenant_id == tenant_id)
            if modalities is not None:
                selected_modalities = tuple(dict.fromkeys(modalities))
                if not selected_modalities:
                    return None
                predicates.append(GenerationJobs.modality.in_(selected_modalities))
            row = (
                await self._session.execute(
                    self._job_query()
                    .where(*predicates)
                    .order_by(GenerationJobs.created_at, GenerationJobs.id)
                    .limit(1)
                    .with_for_update(of=GenerationJobs, skip_locked=True)
                )
            ).first()
            if row is None:
                return None
            job, _deployment, _product = row
            result = await self._session.execute(
                update(GenerationJobs)
                .where(
                    GenerationJobs.tenant_id == job.tenant_id,
                    GenerationJobs.job_id == job.job_id,
                    GenerationJobs.status == "accepted",
                    GenerationJobs.lease_token.is_(None),
                )
                .values(
                    status="reserved",
                    started_at=job.started_at or now,
                    claim_owner=worker_id,
                    lease_token=uuid.uuid4(),
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    fencing_token=int(job.fencing_token) + 1,
                    updated_at=now,
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                return None
            return await self._get_by_job_id(tenant_id=job.tenant_id, job_id=job.job_id)

    async def claim_pending_reconciliation(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> GenerationRecord | None:
        _validate_claim_input(worker_id, lease_seconds)
        now = datetime.now(UTC)
        async with self._session.begin():
            row = (
                await self._session.execute(
                    self._job_query()
                    .where(
                        GenerationJobs.status == "submitted_unknown",
                        GenerationJobs.reconciliation_status == "pending",
                        GenerationJobs.modality == "video",
                        GenerationJobs.provider_task_id.is_not(None),
                        or_(
                            GenerationJobs.lease_token.is_(None),
                            GenerationJobs.lease_expires_at <= now,
                        ),
                    )
                    .order_by(GenerationJobs.updated_at, GenerationJobs.id)
                    .limit(1)
                    .with_for_update(of=GenerationJobs, skip_locked=True)
                )
            ).first()
            if row is None:
                return None
            job, _deployment, _product = row
            result = await self._session.execute(
                update(GenerationJobs)
                .where(
                    GenerationJobs.id == job.id,
                    GenerationJobs.status == "submitted_unknown",
                    GenerationJobs.reconciliation_status == "pending",
                    or_(
                        GenerationJobs.lease_token.is_(None),
                        GenerationJobs.lease_expires_at <= now,
                    ),
                )
                .values(
                    claim_owner=worker_id,
                    lease_token=uuid.uuid4(),
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    fencing_token=int(job.fencing_token) + 1,
                    updated_at=now,
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                return None
            return await self._get_by_job_id(tenant_id=job.tenant_id, job_id=job.job_id)

    async def release_reconciliation_claim(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        lease_token: uuid.UUID,
        fencing_token: int,
    ) -> None:
        _validate_fence(lease_token, fencing_token)
        async with self._session.begin():
            result = await self._session.execute(
                update(GenerationJobs)
                .where(
                    GenerationJobs.tenant_id == tenant_id,
                    GenerationJobs.job_id == job_id,
                    GenerationJobs.status == "submitted_unknown",
                    GenerationJobs.reconciliation_status == "pending",
                    GenerationJobs.lease_token == lease_token,
                    GenerationJobs.fencing_token == fencing_token,
                )
                .values(
                    claim_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                    updated_at=datetime.now(UTC),
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise GenerationStateConflictError()

    async def _get_by_db_id(
        self, *, tenant_id: uuid.UUID, db_id: uuid.UUID
    ) -> GenerationRecord | None:
        query = self._job_query().where(
            GenerationJobs.tenant_id == tenant_id,
            GenerationJobs.id == db_id,
        )
        row = (await self._session.execute(query)).first()
        return await self._materialize(row, tenant_id=tenant_id) if row else None

    async def _get_by_job_id(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
    ) -> GenerationRecord | None:
        conditions: list[Any] = [
            GenerationJobs.tenant_id == tenant_id,
            GenerationJobs.job_id == job_id,
        ]
        if actor_user_id is not None:
            conditions.append(GenerationJobs.actor_user_id == actor_user_id)
        query = self._job_query().where(*conditions)
        row = (await self._session.execute(query)).first()
        return await self._materialize(row, tenant_id=tenant_id) if row else None

    def _job_query(self) -> Select[Any]:
        return (
            select(GenerationJobs, ModelDeployments, ProductModels)
            .join(ModelDeployments, ModelDeployments.id == GenerationJobs.model_deployment_id)
            .join(ProductModels, ProductModels.id == ModelDeployments.product_model_id)
        )

    async def _materialize(self, row: Any, *, tenant_id: uuid.UUID) -> GenerationRecord:
        job, deployment, product = row
        artifact_rows = (
            await self._session.execute(
                select(GenerationArtifacts).where(
                    GenerationArtifacts.tenant_id == tenant_id,
                    GenerationArtifacts.generation_job_id == job.id,
                )
            )
        ).scalars()
        artifacts = tuple(_public_artifact(artifact) for artifact in artifact_rows)
        return _record_from_job(
            job,
            product.model_key,
            artifacts,
            concurrency_limit=int(deployment.concurrency_limit),
        )

    async def renew_lease(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        lease_token: uuid.UUID,
        fencing_token: int,
        lease_seconds: int,
    ) -> GenerationRecord:
        _validate_claim_input(worker_id, lease_seconds)
        _validate_fence(lease_token, fencing_token)
        now = datetime.now(UTC)
        async with self._session.begin():
            result = await self._session.execute(
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
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    updated_at=now,
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise GenerationStateConflictError()
            record = await self._get_by_job_id(tenant_id=tenant_id, job_id=job_id)
            if record is None:
                raise GenerationNotFoundError()
            return record

    async def transition(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        expected: GenerationStatus,
        target: GenerationStatus,
        error_code: str | None = None,
        provider_request_id: str | None = None,
        provider_task_id: str | None = None,
        provider_observed_status: str | None = None,
        lease_token: uuid.UUID,
        fencing_token: int,
    ) -> GenerationRecord:
        assert_transition(expected, target)
        _validate_fence(lease_token, fencing_token)
        if error_code is not None and _ERROR_CODE_RE.fullmatch(error_code) is None:
            raise ValueError("error_code must contain only uppercase letters, digits, and underscores")
        now = datetime.now(UTC)
        async with self._session.begin():
            values: dict[str, Any] = {"status": target, "updated_at": now}
            if target in {"failed", "cancelled", "expired", "succeeded"}:
                values["completed_at"] = now
            if target in {"accepted", "submitted_unknown", "failed", "cancelled", "expired", "succeeded"}:
                values.update(
                    claim_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                )
            if target == "submitted_unknown":
                values["reconciliation_status"] = "pending"
            if error_code is not None:
                values["error_code"] = error_code
            if provider_request_id is not None:
                values["provider_request_id"] = provider_request_id
            if provider_task_id is not None:
                values["provider_task_id"] = provider_task_id
            if provider_observed_status is not None:
                if not provider_observed_status.strip() or len(provider_observed_status) > 64:
                    raise ValueError("provider observed status is invalid")
                values["provider_observed_status"] = provider_observed_status
                values["provider_observed_at"] = now
            result = await self._session.execute(
                update(GenerationJobs)
                .where(
                    GenerationJobs.tenant_id == tenant_id,
                    GenerationJobs.job_id == job_id,
                    GenerationJobs.status == expected,
                    GenerationJobs.lease_token == lease_token,
                    GenerationJobs.fencing_token == fencing_token,
                    GenerationJobs.lease_expires_at > now,
                )
                .values(**values)
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise GenerationStateConflictError()
            record = await self._get_by_job_id(tenant_id=tenant_id, job_id=job_id)
            if record is None:
                raise GenerationNotFoundError()
            return record

    async def record_provider_task(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        provider_task_id: str,
        lease_token: uuid.UUID,
        fencing_token: int,
    ) -> None:
        _validate_fence(lease_token, fencing_token)
        if not provider_task_id.strip() or len(provider_task_id) > 255:
            raise ValueError("provider_task_id is invalid")
        async with self._session.begin():
            result = await self._session.execute(
                update(GenerationJobs)
                .where(
                    GenerationJobs.tenant_id == tenant_id,
                    GenerationJobs.job_id == job_id,
                    GenerationJobs.status == "submitted",
                    GenerationJobs.provider_task_id.is_(None),
                    GenerationJobs.lease_token == lease_token,
                    GenerationJobs.fencing_token == fencing_token,
                    GenerationJobs.lease_expires_at > datetime.now(UTC),
                )
                .values(provider_task_id=provider_task_id, updated_at=datetime.now(UTC))
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise GenerationStateConflictError()

    async def record_provider_request(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        provider_request_id: str,
        lease_token: uuid.UUID,
        fencing_token: int,
    ) -> None:
        _validate_fence(lease_token, fencing_token)
        if not provider_request_id.strip() or len(provider_request_id) > 255:
            raise ValueError("provider_request_id is invalid")
        async with self._session.begin():
            result = await self._session.execute(
                update(GenerationJobs)
                .where(
                    GenerationJobs.tenant_id == tenant_id,
                    GenerationJobs.job_id == job_id,
                    GenerationJobs.status == "submitted",
                    GenerationJobs.provider_request_id.is_(None),
                    GenerationJobs.lease_token == lease_token,
                    GenerationJobs.fencing_token == fencing_token,
                    GenerationJobs.lease_expires_at > datetime.now(UTC),
                )
                .values(provider_request_id=provider_request_id, updated_at=datetime.now(UTC))
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise GenerationStateConflictError()

    async def complete(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        expected: GenerationStatus,
        artifacts: Sequence[GenerationArtifactInput],
        usage: GenerationUsage,
        provider_request_id: str | None = None,
        provider_task_id: str | None = None,
        lease_token: uuid.UUID,
        fencing_token: int,
    ) -> GenerationRecord:
        """Persist artifacts, usage, and the terminal state in one short txn."""

        assert_transition(expected, "succeeded")
        if expected != "storing":
            raise ValueError("generation completion must use the storing state")
        _validate_fence(lease_token, fencing_token)
        _validate_usage(usage)
        now = datetime.now(UTC)
        async with self._session.begin():
            job = (
                await self._session.execute(
                    select(GenerationJobs)
                    .where(
                        GenerationJobs.tenant_id == tenant_id,
                        GenerationJobs.job_id == job_id,
                        GenerationJobs.lease_token == lease_token,
                        GenerationJobs.fencing_token == fencing_token,
                        GenerationJobs.lease_expires_at > now,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if job is None:
                raise GenerationNotFoundError()
            if job.status != expected:
                raise GenerationStateConflictError()
            price = await _price_for_job(self._session, job)
            charge = charge_for_usage(price, _billing_usage(usage))

            existing_artifacts = (
                await self._session.execute(
                    select(GenerationArtifacts.id).where(
                        GenerationArtifacts.tenant_id == tenant_id,
                        GenerationArtifacts.generation_job_id == job.id,
                    )
                )
            ).scalars()
            if tuple(existing_artifacts):
                raise GenerationStateConflictError()
            product_model_id = (
                await self._get_by_job_id(tenant_id=tenant_id, job_id=job_id)
            )
            if product_model_id is None:
                raise GenerationNotFoundError()
            for item in artifacts:
                _validate_artifact_input(item)
                stored = item.stored
                self._session.add(
                    GenerationArtifacts(
                        id=uuid.uuid4(),
                        tenant_id=tenant_id,
                        generation_job_id=job.id,
                        kind=item.kind,
                        status="ready",
                        storage_provider=stored.storage_provider,
                        object_key=stored.object_key,
                        mime_type=stored.mime_type,
                        size_bytes=stored.size_bytes,
                        sha256=stored.sha256,
                        expires_at=stored.expires_at,
                    )
                )

            usage_exists = (
                await self._session.execute(
                    select(UsageRecords.id).where(
                        UsageRecords.tenant_id == tenant_id,
                        UsageRecords.generation_job_id == job.id,
                    )
                )
            ).scalar_one_or_none()
            if usage_exists is not None:
                raise GenerationStateConflictError()
            self._session.add(
                UsageRecords(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    actor_user_id=job.actor_user_id,
                    inference_request_id=None,
                    generation_job_id=job.id,
                    model_deployment_id=job.model_deployment_id,
                    modality=job.modality,
                    model_key=product_model_id.product_model_id,
                    provider_request_id=provider_request_id or job.provider_request_id,
                    provider_task_id=provider_task_id or job.provider_task_id,
                    pricing_version=pricing_version(price),
                    currency=price.currency,
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
                    charge_amount_minor=charge.amount_minor,
                )
            )
            values: dict[str, Any] = {
                "status": "succeeded",
                "completed_at": now,
                "updated_at": now,
                "error_code": None,
                "claim_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "reconciliation_status": "not_required",
            }
            if provider_request_id is not None:
                values["provider_request_id"] = provider_request_id
            if provider_task_id is not None:
                values["provider_task_id"] = provider_task_id
            result = await self._session.execute(
                update(GenerationJobs)
                .where(
                    GenerationJobs.tenant_id == tenant_id,
                    GenerationJobs.job_id == job_id,
                    GenerationJobs.status == expected,
                    GenerationJobs.lease_token == lease_token,
                    GenerationJobs.fencing_token == fencing_token,
                    GenerationJobs.lease_expires_at > now,
                )
                .values(**values)
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise GenerationStateConflictError()
            record = await self._get_by_job_id(tenant_id=tenant_id, job_id=job_id)
            if record is None:
                raise GenerationNotFoundError()
            return record

    async def record_inbox_event(
        self,
        *,
        tenant_id: uuid.UUID,
        provider_name: str,
        event_key: str,
        event_type: str,
        normalized_payload: Mapping[str, object],
    ) -> bool:
        for value, maximum, label in (
            (provider_name, 64, "provider name"),
            (event_key, 255, "event key"),
            (event_type, 160, "event type"),
        ):
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"inbox {label} is invalid")
        payload = dict(normalized_payload)
        payload_digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        inbox_id = uuid.uuid4()
        async with self._session.begin():
            result = await self._session.execute(
                pg_insert(InboxEvents)
                .values(
                    id=inbox_id,
                    tenant_id=tenant_id,
                    provider_name=provider_name,
                    event_key=event_key,
                    event_type=event_type,
                    payload_digest=payload_digest,
                    normalized_payload=payload,
                    status="received",
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        InboxEvents.tenant_id,
                        InboxEvents.provider_name,
                        InboxEvents.event_key,
                    ]
                )
                .returning(InboxEvents.id)
            )
            inserted_id = result.scalar_one_or_none()
            if inserted_id is not None:
                return True
            existing = (
                await self._session.execute(
                    select(InboxEvents).where(
                        InboxEvents.tenant_id == tenant_id,
                        InboxEvents.provider_name == provider_name,
                        InboxEvents.event_key == event_key,
                    )
                )
            ).scalar_one_or_none()
            if existing is None or existing.payload_digest != payload_digest:
                raise GenerationStateConflictError()
            return False

    async def claim_outbox(
        self,
        *,
        limit: int = 50,
        tenant_id: uuid.UUID | None = None,
        lease_seconds: int = 60,
    ) -> Sequence[OutboxRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("outbox claim limit must be between 1 and 500")
        if lease_seconds < 1:
            raise ValueError("outbox lease must be positive")
        now = datetime.now(UTC)
        async with self._session.begin():
            query = (
                select(OutboxEvents)
                .where(
                    OutboxEvents.status == "pending",
                    OutboxEvents.available_at <= now,
                    *([OutboxEvents.tenant_id == tenant_id] if tenant_id else []),
                )
                .order_by(OutboxEvents.created_at, OutboxEvents.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = tuple((await self._session.execute(query)).scalars())
            lease_until = now + timedelta(seconds=lease_seconds)
            for row in rows:
                row.attempts += 1
                row.available_at = lease_until
            return tuple(_outbox_record(row) for row in rows)

    async def mark_outbox_published(
        self,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        aggregate_version: int,
    ) -> bool:
        async with self._session.begin():
            result = await self._session.execute(
                update(OutboxEvents)
                .where(
                    OutboxEvents.tenant_id == tenant_id,
                    OutboxEvents.id == event_id,
                    OutboxEvents.aggregate_version == aggregate_version,
                    OutboxEvents.status == "pending",
                )
                .values(
                    status="published",
                    published_at=datetime.now(UTC),
                    sanitized_error_details=None,
                )
            )
            return cast(CursorResult[Any], result).rowcount == 1

    async def mark_outbox_failed(
        self,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        aggregate_version: int,
        details: Mapping[str, Any],
    ) -> bool:
        # Only a tiny, typed whitelist belongs in the database.  Raw provider
        # bodies, URLs, exception strings, and arbitrary metadata stay out.
        safe_details: dict[str, str | bool] = {}
        for key in _SAFE_OUTBOX_ERROR_KEYS:
            value = details.get(key)
            if key == "retryable":
                if isinstance(value, bool):
                    safe_details[key] = value
            elif isinstance(value, str):
                normalized = value.strip()
                if (
                    (key == "code" and _ERROR_CODE_RE.fullmatch(normalized))
                    or (key == "phase" and re.fullmatch(r"^[a-z_]{1,64}$", normalized))
                ):
                    safe_details[key] = normalized
        async with self._session.begin():
            result = await self._session.execute(
                update(OutboxEvents)
                .where(
                    OutboxEvents.tenant_id == tenant_id,
                    OutboxEvents.id == event_id,
                    OutboxEvents.aggregate_version == aggregate_version,
                    OutboxEvents.status == "pending",
                )
                .values(status="failed", sanitized_error_details=safe_details)
            )
            return cast(CursorResult[Any], result).rowcount == 1


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


async def _price_for_job(session: AsyncSession, job: GenerationJobs) -> PriceSnapshot:
    if job.accepted_price_version_id is None:
        raise GenerationInfrastructureError("GENERATION_PRICE_SNAPSHOT_MISSING")
    price = (
        await session.execute(
            select(PriceVersions).where(PriceVersions.id == job.accepted_price_version_id)
        )
    ).scalar_one_or_none()
    if price is None:
        raise GenerationInfrastructureError("GENERATION_PRICE_SNAPSHOT_MISSING")
    return PriceSnapshot(
        price_version_id=price.id,
        price_key=price.price_key,
        version=int(price.version),
        currency=price.currency,
        unit=price.unit,
        pricing=dict(price.pricing or {}),
    )


def _record_from_job(
    job: GenerationJobs,
    product_model_id: str,
    artifacts: tuple[PublicArtifact, ...],
    *,
    concurrency_limit: int = 1,
) -> GenerationRecord:
    return GenerationRecord(
        db_id=job.id,
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        actor_user_id=job.actor_user_id,
        product_model_id=product_model_id,
        modality=cast(GenerationModality, job.modality),
        status=cast(GenerationStatus, job.status),
        request_payload=dict(job.request_payload or {}),
        created_at=_as_utc(job.created_at),
        updated_at=_as_utc(job.updated_at),
        completed_at=_as_utc(job.completed_at) if job.completed_at else None,
        error_code=job.error_code,
        model_deployment_id=job.model_deployment_id,
        concurrency_limit=concurrency_limit,
        billing_reservation_id=getattr(job, "billing_reservation_id", None),
        claim_owner=getattr(job, "claim_owner", None),
        lease_token=getattr(job, "lease_token", None),
        lease_expires_at=_optional_utc(getattr(job, "lease_expires_at", None)),
        fencing_token=int(getattr(job, "fencing_token", 0)),
        reconciliation_status=str(getattr(job, "reconciliation_status", "not_required")),
        provider_request_id=job.provider_request_id,
        provider_task_id=job.provider_task_id,
        artifacts=artifacts,
    )


def _public_artifact(artifact: GenerationArtifacts) -> PublicArtifact:
    return PublicArtifact(
        artifact_id=artifact.id,
        kind=artifact.kind,
        status=artifact.status,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
    )


def _outbox_record(row: OutboxEvents) -> OutboxRecord:
    return OutboxRecord(
        event_id=row.id,
        tenant_id=row.tenant_id,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        aggregate_version=row.aggregate_version,
        payload=dict(row.payload or {}),
        attempts=row.attempts,
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


def _validate_claim_input(worker_id: str, lease_seconds: int) -> None:
    if not worker_id.strip() or len(worker_id) > 200:
        raise ValueError("generation claim owner is invalid")
    if not 1 <= lease_seconds <= 3_600:
        raise ValueError("generation lease must be between 1 and 3600 seconds")


def _validate_fence(lease_token: uuid.UUID, fencing_token: int) -> None:
    if not isinstance(lease_token, uuid.UUID):
        raise TypeError("generation lease token must be a UUID")
    if isinstance(fencing_token, bool) or not isinstance(fencing_token, int) or fencing_token < 1:
        raise ValueError("generation fencing token must be positive")


def _validate_artifact_input(item: GenerationArtifactInput) -> None:
    if item.kind not in {"output", "thumbnail", "preview", "input"}:
        raise ValueError("unsupported generation artifact kind")
    stored = item.stored
    if (
        not stored.storage_provider.strip()
        or not stored.object_key.strip()
        or stored.object_key.startswith(("/", "\\"))
        or ".." in stored.object_key.replace("\\", "/").split("/")
        or not stored.mime_type.strip()
        or stored.size_bytes < 0
    ):
        raise ValueError("invalid stored generation artifact")


def _validate_usage(usage: GenerationUsage) -> None:
    # Keep this check close to the persistence boundary as a defense against a
    # fake/provider adapter accidentally writing negative accounting measures.
    values = (
        usage.input_tokens,
        usage.output_tokens,
        usage.image_count,
        usage.video_seconds,
        usage.audio_seconds,
        usage.character_count,
        usage.audio_duration_ms,
        usage.video_duration_ms,
        usage.storage_bytes,
        usage.billable_units,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        raise ValueError("generation usage values must be non-negative integers")


__all__ = [
    "AcceptedGeneration",
    "DeploymentRoute",
    "GenerationRecord",
    "GenerationRepository",
    "OutboxRecord",
    "PublicArtifact",
    "RouteUnavailable",
    "SqlAlchemyGenerationRepository",
    "canonical_request_hash",
]
