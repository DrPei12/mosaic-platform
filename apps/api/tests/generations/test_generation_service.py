from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.contracts.generations import CreateGenerationRequest
from app.generations.errors import IdempotencyConflictError, ModelUnavailableError
from app.generations.repository import (
    AcceptedGeneration,
    GenerationRecord,
    OutboxRecord,
    canonical_request_hash,
)
from app.generations.service import GenerationService
from app.generations.state import InvalidGenerationTransition, assert_transition

TENANT_A = UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = UUID("00000000-0000-0000-0000-000000000002")
USER_A = UUID("00000000-0000-0000-0000-000000000011")
USER_B = UUID("00000000-0000-0000-0000-000000000012")


def request(*, client_request_id: str = "req-1") -> CreateGenerationRequest:
    return CreateGenerationRequest(
        product_model_id="qwen-3-5-plus",
        modality="text",
        input={"prompt": "hello"},
        client_request_id=client_request_id,
    )


def record(
    *,
    tenant_id: UUID,
    actor_user_id: UUID = USER_A,
    job_id: UUID | None = None,
    status: str = "accepted",
    product_model_id: str = "qwen-3-5-plus",
) -> GenerationRecord:
    now = datetime.now(UTC)
    job_id = job_id or uuid4()
    return GenerationRecord(
        db_id=uuid4(),
        job_id=job_id,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        product_model_id=product_model_id,
        modality="text",
        status=status,  # type: ignore[arg-type]
        request_payload={"prompt": "hello"},
        created_at=now,
        updated_at=now,
        completed_at=None,
        error_code=None,
        model_deployment_id=uuid4(),
        artifacts=(),
    )


class FakeGenerationRepository:
    def __init__(self, *, route_available: bool = True) -> None:
        self.route_available = route_available
        self.records: dict[tuple[UUID, UUID, str], GenerationRecord] = {}
        self.idempotency: dict[tuple[UUID, UUID, str], tuple[str, GenerationRecord]] = {}
        self.events: list[OutboxRecord] = []

    async def accept(self, *, tenant_id, actor_user_id, request, request_hash):
        if not self.route_available:
            raise ModelUnavailableError()
        key = (tenant_id, actor_user_id, request.client_request_id)
        existing = self.idempotency.get(key)
        if existing is not None:
            old_hash, old_record = existing
            if old_hash != request_hash:
                raise IdempotencyConflictError()
            return AcceptedGeneration(record=old_record, replayed=True)
        job = record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            product_model_id=request.product_model_id,
        )
        self.records[(tenant_id, actor_user_id, str(job.job_id))] = job
        self.idempotency[key] = (request_hash, job)
        self.events.append(
            OutboxRecord(
                event_id=uuid4(),
                tenant_id=tenant_id,
                aggregate_type="generation_job",
                aggregate_id=job.db_id,
                event_type="generation.accepted",
                aggregate_version=1,
                payload={"job_id": str(job.job_id)},
                attempts=0,
            )
        )
        return AcceptedGeneration(record=job, replayed=False)

    async def get(self, *, tenant_id, actor_user_id, job_id):
        return self.records.get((tenant_id, actor_user_id, str(job_id)))

    async def list_recent(self, *, tenant_id, actor_user_id, limit=50):
        values = [
            record
            for (scope, actor, _), record in self.records.items()
            if scope == tenant_id and actor == actor_user_id
        ]
        return tuple(values[:limit])

    async def transition(self, *, tenant_id, job_id, expected, target, error_code=None):
        key = next(
            key
            for key in self.records
            if key[0] == tenant_id and key[2] == str(job_id)
        )
        job = self.records[key]
        if job.status != expected:
            raise InvalidGenerationTransition("CAS failed")
        assert_transition(expected, target)
        assert job.actor_user_id is not None
        updated = record(
            tenant_id=tenant_id,
            actor_user_id=job.actor_user_id,
            job_id=job.job_id,
            status=target,
            product_model_id=job.product_model_id,
        )
        self.records[(tenant_id, job.actor_user_id, str(job_id))] = updated
        return updated

    async def claim_outbox(self, *, limit=50, tenant_id=None, lease_seconds=60):
        del lease_seconds
        values = [event for event in self.events if tenant_id is None or event.tenant_id == tenant_id]
        return tuple(values[:limit])

    async def mark_outbox_published(self, *, tenant_id, event_id, aggregate_version):
        return any(
            event.tenant_id == tenant_id
            and event.event_id == event_id
            and event.aggregate_version == aggregate_version
            for event in self.events
        )

    async def mark_outbox_failed(
        self, *, tenant_id, event_id, aggregate_version, details
    ):
        del details
        return await self.mark_outbox_published(
            tenant_id=tenant_id,
            event_id=event_id,
            aggregate_version=aggregate_version,
        )


@pytest.mark.asyncio
async def test_accept_is_idempotent_and_writes_one_outbox_event() -> None:
    repository = FakeGenerationRepository()
    service = GenerationService(repository)  # type: ignore[arg-type]
    payload = request()

    first = await service.accept(tenant_id=TENANT_A, actor_user_id=USER_A, request=payload)
    second = await service.accept(tenant_id=TENANT_A, actor_user_id=USER_A, request=payload)

    assert first.replayed is False
    assert second.replayed is True
    assert first.record.job_id == second.record.job_id
    assert len(repository.events) == 1


@pytest.mark.asyncio
async def test_same_key_with_different_payload_is_rejected() -> None:
    repository = FakeGenerationRepository()
    service = GenerationService(repository)  # type: ignore[arg-type]
    await service.accept(tenant_id=TENANT_A, actor_user_id=USER_A, request=request())

    with pytest.raises(IdempotencyConflictError):
        await service.accept(
            tenant_id=TENANT_A,
            actor_user_id=USER_A,
            request=CreateGenerationRequest(
                product_model_id="qwen-3-5-plus",
                modality="text",
                input={"prompt": "different"},
                client_request_id="req-1",
            ),
        )


@pytest.mark.asyncio
async def test_get_is_strictly_tenant_scoped() -> None:
    repository = FakeGenerationRepository()
    service = GenerationService(repository)  # type: ignore[arg-type]
    accepted = await service.accept(tenant_id=TENANT_A, actor_user_id=USER_A, request=request())

    with pytest.raises(Exception) as error:
        await service.get(
            tenant_id=TENANT_B,
            actor_user_id=USER_A,
            job_id=accepted.record.job_id,
        )
    assert getattr(error.value, "code", None) == "GENERATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_recent_generation_list_is_tenant_scoped() -> None:
    repository = FakeGenerationRepository()
    service = GenerationService(repository)  # type: ignore[arg-type]
    first = await service.accept(tenant_id=TENANT_A, actor_user_id=USER_A, request=request())
    await service.accept(
        tenant_id=TENANT_B,
        actor_user_id=USER_A,
        request=request(client_request_id="tenant-b"),
    )

    recent = await service.list_recent(tenant_id=TENANT_A, actor_user_id=USER_A)

    assert [item.job_id for item in recent] == [str(first.record.job_id)]


@pytest.mark.asyncio
async def test_same_tenant_generation_list_and_get_are_actor_scoped() -> None:
    repository = FakeGenerationRepository()
    service = GenerationService(repository)  # type: ignore[arg-type]
    own = await service.accept(tenant_id=TENANT_A, actor_user_id=USER_A, request=request())
    other = await service.accept(
        tenant_id=TENANT_A,
        actor_user_id=USER_B,
        request=request(client_request_id="user-b"),
    )

    assert [item.job_id for item in await service.list_recent(
        tenant_id=TENANT_A,
        actor_user_id=USER_A,
    )] == [str(own.record.job_id)]
    with pytest.raises(Exception) as error:
        await service.get(
            tenant_id=TENANT_A,
            actor_user_id=USER_A,
            job_id=other.record.job_id,
        )
    assert getattr(error.value, "code", None) == "GENERATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_unavailable_route_does_not_create_job_or_event() -> None:
    repository = FakeGenerationRepository(route_available=False)
    service = GenerationService(repository)  # type: ignore[arg-type]

    with pytest.raises(ModelUnavailableError):
        await service.accept(tenant_id=TENANT_A, actor_user_id=USER_A, request=request())
    assert repository.records == {}
    assert repository.events == []


def test_canonical_hash_is_stable_for_normalized_payload() -> None:
    assert canonical_request_hash(request()) == canonical_request_hash(request())
