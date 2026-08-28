from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Self
from uuid import UUID, uuid4

import pytest

from app.billing.ports import Money, ReleaseResult, ReservationResult
from app.generations.ports import ProviderPorts, StoredArtifact
from app.generations.recovery import GenerationRecoveryService, GenerationVideoRecoveryWorker
from app.generations.repository import GenerationRecord
from app.providers.ports import (
    RemoteAsset,
    VideoTaskResult,
    VideoTaskStatus,
    VideoUsage,
)


class _Result:
    def __init__(self, job: object) -> None:
        self._job = job

    def scalar_one_or_none(self) -> object:
        return self._job

    def scalars(self) -> tuple[object, ...]:
        return (self._job,)


class _Session:
    def __init__(self, job: object, audit_rows: list[object]) -> None:
        self._job = job
        self._audit_rows = audit_rows

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> Self:
        return self

    async def execute(self, _statement: object) -> _Result:
        return _Result(self._job)

    def add(self, row: object) -> None:
        self._audit_rows.append(row)


class _Sessions:
    def __init__(self, job: object) -> None:
        self.audit_rows: list[object] = []
        self._job = job

    def __call__(self) -> _Session:
        return _Session(self._job, self.audit_rows)


@pytest.mark.asyncio
async def test_failed_operator_resolution_is_audited_released_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    job_id = uuid4()
    reservation_id = uuid4()
    job = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        job_id=job_id,
        modality="video",
        status="submitted_unknown",
        reconciliation_status="pending",
        provider_request_id=None,
        provider_task_id="task-1",
        provider_observed_status=None,
        provider_observed_at=None,
        billing_reservation_id=reservation_id,
        error_code="GENERATION_RECONCILIATION_REQUIRED",
        completed_at=None,
        updated_at=datetime.now(UTC),
    )
    sessions = _Sessions(job)
    released: list[tuple[object, object]] = []

    async def release(_self: object, **kwargs: Any) -> ReleaseResult:
        released.append((kwargs["tenant_id"], kwargs["reservation_id"]))
        reservation = ReservationResult(
            reservation_id=reservation_id,
            tenant_id=tenant_id,
            source_type="generation",
            source_id=job.id,
            amount=Money(100, "PTS"),
            status="released",
            expires_at=datetime.now(UTC),
        )
        return ReleaseResult(reservation=reservation, released=reservation.amount, idempotent=False)

    monkeypatch.setattr("app.generations.recovery.SqlAlchemyBillingService.release", release)
    service = GenerationRecoveryService(sessions)  # type: ignore[arg-type]

    await service.resolve_failed(
        tenant_id=tenant_id,
        job_id=job_id,
        operator_subject="operator:test",
        reason="provider confirmed no chargeable output",
    )

    assert job.status == "failed"
    assert job.reconciliation_status == "resolved"
    assert job.provider_observed_status == "FAILED"
    assert released == [(tenant_id, reservation_id)]
    assert [row.action for row in sessions.audit_rows] == [
        "generation.reconciliation.failed_requested",
        "generation.reconciliation.resolved",
    ]

    await service.resolve_failed(
        tenant_id=tenant_id,
        job_id=job_id,
        operator_subject="operator:test",
        reason="idempotent retry",
    )
    assert released == [(tenant_id, reservation_id)]


@pytest.mark.asyncio
async def test_pending_recovery_list_is_bounded() -> None:
    job = SimpleNamespace(
        tenant_id=uuid4(),
        job_id=uuid4(),
        modality="video",
        provider_request_id=None,
        provider_task_id="task-1",
        updated_at=datetime.now(UTC),
    )
    service = GenerationRecoveryService(_Sessions(job))  # type: ignore[arg-type]

    rows = await service.list_pending(limit=1)

    assert len(rows) == 1
    with pytest.raises(ValueError):
        await service.list_pending(limit=501)


class _VideoProvider:
    async def get_video_task(self, task_id: str) -> VideoTaskResult:
        return VideoTaskResult(
            task_id=task_id,
            status=VideoTaskStatus.SUCCEEDED,
            video=RemoteAsset.from_url("https://assets.aliyuncs.com/recovered.mp4?sig=x"),
            request_id="request-1",
            usage=VideoUsage(duration_seconds=2, video_count=1),
        )


class _Resolver:
    async def resolve(self, **_kwargs: Any) -> ProviderPorts:
        return ProviderPorts(video=_VideoProvider(), provider_model_id="wan2.7-t2v")


class _Storage:
    async def transfer_remote(self, **_kwargs: Any) -> StoredArtifact:
        return StoredArtifact(
            storage_provider="s3",
            object_key="tenant/job/output.mp4",
            mime_type="video/mp4",
            size_bytes=10,
            sha256="a" * 64,
        )


class _RecoveryRepository:
    def __init__(self, job: GenerationRecord) -> None:
        self.job = job
        self.transitions: list[tuple[str, str]] = []
        self.completed = False

    async def claim_pending_reconciliation(self, **_kwargs: Any) -> GenerationRecord | None:
        return self.job

    async def release_reconciliation_claim(self, **_kwargs: Any) -> None:
        raise AssertionError("successful recovery must not release before completion")

    async def transition(self, *, expected: str, target: str, **kwargs: Any) -> GenerationRecord:
        assert self.job.status == expected
        self.transitions.append((expected, target))
        values = {field: getattr(self.job, field) for field in self.job.__dataclass_fields__}
        values["status"] = target
        if kwargs.get("provider_request_id") is not None:
            values["provider_request_id"] = kwargs["provider_request_id"]
        self.job = GenerationRecord(**values)
        return self.job

    async def complete(self, **_kwargs: Any) -> GenerationRecord:
        values = {field: getattr(self.job, field) for field in self.job.__dataclass_fields__}
        values["status"] = "succeeded"
        self.job = GenerationRecord(**values)
        self.completed = True
        return self.job


class _Billing:
    def __init__(self) -> None:
        self.captured: list[tuple[UUID, UUID]] = []

    async def capture(self, *, tenant_id: UUID, reservation_id: UUID, **_kwargs: Any) -> object:
        self.captured.append((tenant_id, reservation_id))
        return object()

    async def release(self, **_kwargs: Any) -> object:
        return object()


@pytest.mark.asyncio
async def test_video_recovery_queries_existing_task_without_resubmission() -> None:
    now = datetime.now(UTC)
    reservation_id = uuid4()
    job = GenerationRecord(
        db_id=uuid4(),
        job_id=uuid4(),
        tenant_id=uuid4(),
        actor_user_id=uuid4(),
        product_model_id="wan-2-7",
        modality="video",
        status="submitted_unknown",
        request_payload={"input": {"prompt": "river", "duration_seconds": 2}},
        created_at=now,
        updated_at=now,
        completed_at=None,
        error_code="GENERATION_RECONCILIATION_REQUIRED",
        model_deployment_id=uuid4(),
        billing_reservation_id=reservation_id,
        claim_owner="reconciler",
        lease_token=uuid4(),
        lease_expires_at=now,
        fencing_token=2,
        reconciliation_status="pending",
        provider_task_id="task-1",
    )
    repository = _RecoveryRepository(job)
    billing = _Billing()
    worker = GenerationVideoRecoveryWorker(
        repository=repository,  # type: ignore[arg-type]
        provider_resolver=_Resolver(),  # type: ignore[arg-type]
        artifact_storage=_Storage(),  # type: ignore[arg-type]
        billing=billing,  # type: ignore[arg-type]
        recovery=SimpleNamespace(resolve_failed=None),  # type: ignore[arg-type]
    )

    assert await worker.run_once() is True
    assert repository.transitions == [
        ("submitted_unknown", "running"),
        ("running", "storing"),
    ]
    assert repository.completed is True
    assert billing.captured == [(job.tenant_id, reservation_id)]
