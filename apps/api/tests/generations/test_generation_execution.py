from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Self, cast
from uuid import UUID, uuid4

import httpx
import pytest

from app.billing.ports import BillingPort, CaptureResult, Money, ReleaseResult, ReservationResult
from app.generations.errors import GenerationInfrastructureError
from app.generations.executor import DashScopeGenerationExecutor
from app.generations.ports import (
    AudioVoiceBinding,
    GenerationExecutionResult,
    GenerationUsage,
    ProviderPorts,
    StoredArtifact,
)
from app.generations.repository import GenerationRecord, OutboxRecord
from app.generations.storage import LocalArtifactStorage
from app.generations.worker import (
    DurableGenerationWorker,
    SqlAlchemyGenerationHeartbeat,
    WorkerDependencies,
)
from app.infrastructure.concurrency import ConcurrencySaturated
from app.providers.errors import ProviderError
from app.providers.ports import (
    AudioGenerationResult,
    AudioUsage,
    ImageArtifact,
    ImageGenerationResult,
    RemoteAsset,
    VideoTaskResult,
    VideoTaskStatus,
    VideoUsage,
)


class _Storage:
    def __init__(self) -> None:
        self.remote_urls: list[str] = []

    async def transfer_remote(self, *, remote_url: str, **kwargs: Any) -> StoredArtifact:
        del kwargs
        self.remote_urls.append(remote_url)
        return StoredArtifact("fake", "tenant/job/output.bin", "application/octet-stream", 3)

    async def put_bytes(self, *, content: bytes, **kwargs: Any) -> StoredArtifact:
        del kwargs
        return StoredArtifact("fake", "tenant/job/output.bin", "image/png", len(content))


class _FailingStorage(_Storage):
    async def transfer_remote(self, *, remote_url: str, **kwargs: Any) -> StoredArtifact:
        del remote_url, kwargs
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_DOWNLOAD_FAILED")

    async def put_bytes(self, *, content: bytes, **kwargs: Any) -> StoredArtifact:
        del content, kwargs
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_WRITE_FAILED")


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> list[object]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> _FakeSession:
        return self

    async def execute(self, _statement: object) -> _FakeResult:
        return _FakeResult(self._rows)


class _Image:
    async def generate(self, request: Any) -> ImageGenerationResult:
        assert request.model == "qwen-image-3.0-pro"
        return ImageGenerationResult(
            request_id="image-request-1",
            model=request.model,
            images=(
                ImageArtifact(
                    data_base64=base64.b64encode(b"png").decode("ascii"),
                ),
            ),
        )


class _Audio:
    def __init__(self) -> None:
        self.requested_voice: str | None = None

    async def synthesize(self, request: Any) -> AudioGenerationResult:
        self.requested_voice = request.voice
        return AudioGenerationResult(
            request_id="audio-request-1",
            model=request.model,
            audio=RemoteAsset.from_url("https://assets.aliyuncs.com/audio.wav?sig=x"),
            usage=AudioUsage(characters=len(request.text)),
        )


class _Video:
    async def submit_video(self, request: Any) -> str:
        assert request.model == "wan2.7-t2v"
        return "task-1"

    async def wait_for_video(self, task_id: str) -> VideoTaskResult:
        return VideoTaskResult(
            task_id=task_id,
            status=VideoTaskStatus.SUCCEEDED,
            video=RemoteAsset.from_url("https://assets.aliyuncs.com/video.mp4?sig=x"),
            request_id="video-request-1",
            usage=VideoUsage(duration_seconds=2, video_count=1),
        )

    async def get_video_task(self, task_id: str) -> VideoTaskResult:
        return await self.wait_for_video(task_id)


class _Recorder:
    def __init__(self) -> None:
        self.task_ids: list[str] = []
        self.request_ids: list[str] = []
        self.fences: list[tuple[UUID, int]] = []

    async def record_provider_request(self, *, provider_request_id: str, **kwargs: Any) -> None:
        self.fences.append((kwargs["lease_token"], kwargs["fencing_token"]))
        self.request_ids.append(provider_request_id)

    async def record_provider_task(self, *, provider_task_id: str, **kwargs: Any) -> None:
        self.fences.append((kwargs["lease_token"], kwargs["fencing_token"]))
        self.task_ids.append(provider_task_id)


class _PermitLease:
    ttl_ms = 30_000

    def __init__(self) -> None:
        self.released = False

    async def renew(self) -> bool:
        return not self.released

    async def release(self) -> bool:
        if self.released:
            return False
        self.released = True
        return True


class _PermitSemaphore:
    def __init__(self, *, saturated: bool = False) -> None:
        self.saturated = saturated
        self.calls: list[tuple[str, int, float]] = []
        self.leases: list[_PermitLease] = []

    async def acquire(self, resource: str, *, limit: int, ttl_seconds: float):
        self.calls.append((resource, limit, ttl_seconds))
        if self.saturated:
            return None
        lease = _PermitLease()
        self.leases.append(lease)
        return lease


def _job(modality: str, input_values: dict[str, object]) -> GenerationRecord:
    now = datetime.now(UTC)
    return GenerationRecord(
        db_id=uuid4(),
        job_id=uuid4(),
        tenant_id=uuid4(),
        actor_user_id=uuid4(),
        product_model_id="demo-model",
        modality=modality,  # type: ignore[arg-type]
        status="submitted",
        request_payload={"input": input_values},
        created_at=now,
        updated_at=now,
        completed_at=None,
        error_code=None,
        model_deployment_id=uuid4(),
        billing_reservation_id=uuid4(),
        claim_owner="test-worker",
        lease_token=uuid4(),
        lease_expires_at=now + timedelta(minutes=5),
        fencing_token=1,
    )


@pytest.mark.asyncio
async def test_dashscope_executor_downloads_image_video_and_audio_outputs() -> None:
    storage = _Storage()
    executor = DashScopeGenerationExecutor()
    recorder = _Recorder()

    image = await executor.execute(
        job=_job("image", {"prompt": "red kite"}),
        providers=ProviderPorts(image=_Image(), provider_model_id="qwen-image-3.0-pro"),
        artifact_storage=storage,
        billing=cast(BillingPort, None),
        submission_recorder=recorder,
    )
    video = await executor.execute(
        job=_job("video", {"prompt": "short river"}),
        providers=ProviderPorts(video=_Video(), provider_model_id="wan2.7-t2v"),
        artifact_storage=storage,
        billing=cast(BillingPort, None),
        submission_recorder=recorder,
    )
    audio_provider = _Audio()
    audio = await executor.execute(
        job=_job("audio", {"text": "hello", "voice": "untrusted-public-value"}),
        providers=ProviderPorts(
            audio=audio_provider,
            provider_model_id="qwen3-tts-flash",
            audio_voice=AudioVoiceBinding(
                target_model="qwen3-tts-flash",
                provider_voice_id="trusted-server-voice",
            ),
        ),
        artifact_storage=storage,
        billing=cast(BillingPort, None),
        submission_recorder=recorder,
    )

    assert image.provider_request_id == "image-request-1"
    assert image.artifacts[0].stored.size_bytes == 3
    assert video.provider_task_id == "task-1"
    assert recorder.task_ids == ["task-1"]
    assert recorder.request_ids == ["image-request-1", "video-request-1", "audio-request-1"]
    assert all(isinstance(token, UUID) and fence == 1 for token, fence in recorder.fences)
    assert audio.provider_request_id == "audio-request-1"
    assert audio_provider.requested_voice == "trusted-server-voice"
    assert storage.remote_urls == [
        "https://assets.aliyuncs.com/video.mp4?sig=x",
        "https://assets.aliyuncs.com/audio.wav?sig=x",
    ]


@pytest.mark.asyncio
async def test_executor_records_sync_request_before_artifact_storage() -> None:
    executor = DashScopeGenerationExecutor()
    recorder = _Recorder()

    with pytest.raises(GenerationInfrastructureError) as image_error:
        await executor.execute(
            job=_job("image", {"prompt": "red kite"}),
            providers=ProviderPorts(image=_Image(), provider_model_id="qwen-image-3.0-pro"),
            artifact_storage=_FailingStorage(),
            billing=cast(BillingPort, None),
            submission_recorder=recorder,
        )
    assert image_error.value.code == "GENERATION_ARTIFACT_WRITE_FAILED"

    with pytest.raises(GenerationInfrastructureError) as audio_error:
        await executor.execute(
            job=_job("audio", {"text": "hello"}),
            providers=ProviderPorts(
                audio=_Audio(),
                provider_model_id="qwen3-tts-flash",
                audio_voice=AudioVoiceBinding(
                    target_model="qwen3-tts-flash",
                    provider_voice_id="trusted-server-voice",
                ),
            ),
            artifact_storage=_FailingStorage(),
            billing=cast(BillingPort, None),
            submission_recorder=recorder,
        )
    assert audio_error.value.code == "GENERATION_ARTIFACT_DOWNLOAD_FAILED"
    assert recorder.request_ids == ["image-request-1", "audio-request-1"]


@pytest.mark.asyncio
async def test_local_storage_writes_relative_tenant_job_key_without_provider_url(
    tmp_path: Path,
) -> None:
    tenant_id = uuid4()
    job_id = uuid4()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "assets.aliyuncs.com"
        return httpx.Response(
            200,
            content=b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00media",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        storage = LocalArtifactStorage(root=tmp_path / "artifact-test-root", client=client)
        stored = await storage.transfer_remote(
            tenant_id=tenant_id,
            job_id=job_id,
            remote_url="https://assets.aliyuncs.com/output.mp4?secret=redacted",
            kind="output",
            mime_type="video/mp4",
        )
        assert stored.object_key.startswith(f"{tenant_id}/{job_id}/")
        assert "secret" not in stored.object_key
        assert storage.resolve_object_path(stored.object_key).read_bytes() == (
            b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00media"
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_stalled_reconciliation_never_releases_submitted_or_live_work() -> None:
    now = datetime.now(UTC)
    jobs = [
        SimpleNamespace(status="reserved", error_code=None, updated_at=now - timedelta(hours=1)),
        SimpleNamespace(status="queued", error_code=None, updated_at=now - timedelta(hours=1)),
        SimpleNamespace(status="submitted", error_code=None, updated_at=now - timedelta(hours=1)),
        SimpleNamespace(status="running", error_code=None, updated_at=now - timedelta(hours=1)),
        SimpleNamespace(status="storing", error_code=None, updated_at=now - timedelta(hours=1)),
    ]
    heartbeat = SqlAlchemyGenerationHeartbeat(lambda: _FakeSession(jobs))  # type: ignore[arg-type]

    reconciled = await heartbeat.reconcile_stalled_once(stale_seconds=60)

    assert reconciled == 5
    assert [job.status for job in jobs] == [
        "failed",
        "failed",
        "submitted_unknown",
        "submitted_unknown",
        "submitted_unknown",
    ]
    assert jobs[2].error_code == "GENERATION_RECONCILIATION_REQUIRED"
    assert jobs[3].error_code == "GENERATION_RECONCILIATION_REQUIRED"
    assert jobs[4].error_code == "GENERATION_RECONCILIATION_REQUIRED"


class _NoopHeartbeat:
    async def ensure_live(self, **kwargs: Any) -> None:
        del kwargs


class _Billing:
    def __init__(self) -> None:
        self.captures: list[CaptureResult] = []
        self.releases: list[ReleaseResult] = []

    def _reservation(self, kwargs: dict[str, Any]) -> ReservationResult:
        result = ReservationResult(
            reservation_id=kwargs["reservation_id"],
            tenant_id=kwargs["tenant_id"],
            source_type="generation",
            source_id=uuid4(),
            amount=Money(10_000, "CNY"),
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        return result

    async def capture(self, **kwargs: Any) -> CaptureResult:
        usage = kwargs["usage"]
        assert usage.image_count == 1
        reservation = self._reservation(kwargs)
        charged = Money(1_100, "CNY")
        released = Money(8_900, "CNY")
        result = CaptureResult(reservation, charged, released, False)
        self.captures.append(result)
        return result

    async def release(self, **kwargs: Any) -> ReleaseResult:
        reservation = self._reservation(kwargs)
        result = ReleaseResult(
            reservation,
            reservation.amount,
            False,
        )
        self.releases.append(result)
        return result


class _CaptureFailingBilling(_Billing):
    async def capture(self, **kwargs: Any) -> CaptureResult:
        del kwargs
        raise RuntimeError("capture outcome is unknown")


class _Repository:
    def __init__(self, job: GenerationRecord) -> None:
        self.job = job
        self.claims = 0
        self.transitions: list[tuple[str, str]] = []
        self.completed = False

    async def claim_accepted(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        **kwargs: Any,
    ) -> GenerationRecord | None:
        assert kwargs["worker_id"]
        assert kwargs["lease_seconds"] > 0
        assert (tenant_id, job_id) == (self.job.tenant_id, self.job.job_id)
        if self.job.status != "accepted":
            return None
        self.claims += 1
        return self._set_status("reserved")

    async def transition(self, *, expected: str, target: str, **kwargs: Any) -> GenerationRecord:
        assert self.job.status == expected
        self.transitions.append((expected, target))
        return self._set_status(target)

    async def complete(self, **kwargs: Any) -> GenerationRecord:
        assert kwargs["expected"] == "storing"
        self.completed = True
        return self._set_status("succeeded")

    def _set_status(self, status: str) -> GenerationRecord:
        values = {field: getattr(self.job, field) for field in self.job.__dataclass_fields__}
        values["status"] = status
        self.job = GenerationRecord(**values)
        return self.job


class _CompleteFailingRepository(_Repository):
    async def complete(self, **kwargs: Any) -> GenerationRecord:
        del kwargs
        raise GenerationInfrastructureError("GENERATION_COMPLETION_UNAVAILABLE")


class _Resolver:
    async def resolve(self, **kwargs: Any) -> ProviderPorts:
        del kwargs
        return ProviderPorts(provider_model_id="qwen-image-3.0-pro")


class _Executor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, **kwargs: Any) -> GenerationExecutionResult:
        self.calls += 1
        return GenerationExecutionResult(usage=GenerationUsage(image_count=1))


class _FailingExecutor:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def execute(self, **kwargs: Any) -> GenerationExecutionResult:
        del kwargs
        raise self.error


@pytest.mark.asyncio
async def test_worker_refuses_a_claim_without_database_fence() -> None:
    job = _job("image", {"prompt": "red kite"})
    values = {field: getattr(job, field) for field in job.__dataclass_fields__}
    values.update(
        status="accepted",
        claim_owner=None,
        lease_token=None,
        lease_expires_at=None,
        fencing_token=0,
    )
    repository = _Repository(GenerationRecord(**values))
    executor = _Executor()
    worker = DurableGenerationWorker(
        cast(Any, repository),
        WorkerDependencies(
            provider_resolver=_Resolver(),
            artifact_storage=_Storage(),
            billing=_Billing(),
            executor=executor,
            heartbeat=_NoopHeartbeat(),
            concurrency=_PermitSemaphore(),
        ),
    )
    event = OutboxRecord(
        event_id=uuid4(),
        tenant_id=job.tenant_id,
        aggregate_type="generation_job",
        aggregate_id=job.db_id,
        event_type="generation.accepted",
        aggregate_version=1,
        payload={"job_id": str(job.job_id)},
        attempts=1,
    )

    with pytest.raises(GenerationInfrastructureError) as error:
        await worker.process(event)

    assert error.value.code == "GENERATION_FENCE_MISSING"
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_worker_claim_and_capture_are_not_replayed() -> None:
    job = _job("image", {"prompt": "red kite"})
    job = GenerationRecord(**{**{field: getattr(job, field) for field in job.__dataclass_fields__}, "status": "accepted"})
    repository = _Repository(job)
    billing = _Billing()
    executor = _Executor()
    worker = DurableGenerationWorker(
        cast(Any, repository),
        WorkerDependencies(
            provider_resolver=_Resolver(),
            artifact_storage=_Storage(),
            billing=billing,
            executor=executor,
            heartbeat=_NoopHeartbeat(),
            concurrency=_PermitSemaphore(),
        ),
    )
    event = OutboxRecord(
        event_id=uuid4(),
        tenant_id=job.tenant_id,
        aggregate_type="generation_job",
        aggregate_id=job.db_id,
        event_type="generation.accepted",
        aggregate_version=1,
        payload={"job_id": str(job.job_id)},
        attempts=1,
    )

    await worker.process(event)
    await worker.process(event)

    assert repository.claims == 1
    assert executor.calls == 1
    assert billing.captures[0].charged.amount_minor == 1_100
    assert billing.releases == []
    assert repository.job.status == "succeeded"


@pytest.mark.asyncio
async def test_worker_requeues_saturated_generation_without_provider_or_billing() -> None:
    job = _job("video", {"prompt": "long river"})
    job = GenerationRecord(
        **{**{field: getattr(job, field) for field in job.__dataclass_fields__}, "status": "accepted"}
    )
    repository = _Repository(job)
    billing = _Billing()
    executor = _Executor()
    worker = DurableGenerationWorker(
        cast(Any, repository),
        WorkerDependencies(
            provider_resolver=_Resolver(),
            artifact_storage=_Storage(),
            billing=billing,
            executor=executor,
            heartbeat=_NoopHeartbeat(),
            concurrency=_PermitSemaphore(saturated=True),
            concurrency_retry_delay_seconds=0.05,
        ),
    )
    event = OutboxRecord(
        event_id=uuid4(),
        tenant_id=job.tenant_id,
        aggregate_type="generation_job",
        aggregate_id=job.db_id,
        event_type="generation.accepted",
        aggregate_version=1,
        payload={"job_id": str(job.job_id)},
        attempts=1,
    )

    with pytest.raises(ConcurrencySaturated):
        await worker.process(event)

    assert repository.transitions == [("reserved", "queued"), ("queued", "accepted")]
    assert repository.job.status == "accepted"
    assert executor.calls == 0
    assert billing.captures == []
    assert billing.releases == []


@pytest.mark.asyncio
async def test_worker_does_not_capture_before_terminal_usage_commit() -> None:
    job = _job("image", {"prompt": "red kite"})
    job = GenerationRecord(
        **{**{field: getattr(job, field) for field in job.__dataclass_fields__}, "status": "accepted"}
    )
    repository = _CompleteFailingRepository(job)
    billing = _Billing()
    worker = DurableGenerationWorker(
        cast(Any, repository),
        WorkerDependencies(
            provider_resolver=_Resolver(),
            artifact_storage=_Storage(),
            billing=billing,
            executor=_Executor(),
            heartbeat=_NoopHeartbeat(),
            concurrency=_PermitSemaphore(),
        ),
    )
    event = OutboxRecord(
        event_id=uuid4(),
        tenant_id=job.tenant_id,
        aggregate_type="generation_job",
        aggregate_id=job.db_id,
        event_type="generation.accepted",
        aggregate_version=1,
        payload={"job_id": str(job.job_id)},
        attempts=1,
    )

    with pytest.raises(GenerationInfrastructureError):
        await worker.process(event)

    assert billing.captures == []
    assert len(billing.releases) == 1


@pytest.mark.asyncio
async def test_capture_failure_after_success_keeps_reservation_for_reconciliation() -> None:
    job = _job("image", {"prompt": "red kite"})
    job = GenerationRecord(
        **{**{field: getattr(job, field) for field in job.__dataclass_fields__}, "status": "accepted"}
    )
    repository = _Repository(job)
    billing = _CaptureFailingBilling()
    worker = DurableGenerationWorker(
        cast(Any, repository),
        WorkerDependencies(
            provider_resolver=_Resolver(),
            artifact_storage=_Storage(),
            billing=billing,
            executor=_Executor(),
            heartbeat=_NoopHeartbeat(),
            concurrency=_PermitSemaphore(),
        ),
    )
    event = OutboxRecord(
        event_id=uuid4(),
        tenant_id=job.tenant_id,
        aggregate_type="generation_job",
        aggregate_id=job.db_id,
        event_type="generation.accepted",
        aggregate_version=1,
        payload={"job_id": str(job.job_id)},
        attempts=1,
    )

    with pytest.raises(GenerationInfrastructureError):
        await worker.process(event)

    assert repository.job.status == "succeeded"
    assert billing.releases == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status", "expected_releases"),
    [
        (
            GenerationInfrastructureError("GENERATION_PROVIDER_TASK_FAILED"),
            "failed",
            1,
        ),
        (
            ProviderError(
                provider="dashscope",
                operation="image_generate",
                code="provider_connection_error",
                message="connection failed",
                retryable=True,
            ),
            "submitted_unknown",
            0,
        ),
        (
            ProviderError(
                provider="dashscope",
                operation="image_generate",
                code="provider_submission_unknown",
                message="response read timed out",
            ),
            "submitted_unknown",
            0,
        ),
        (
            ProviderError(
                provider="dashscope",
                operation="video_task",
                code="provider_poll_transport_error",
                message="poll transport failed",
                retryable=True,
            ),
            "submitted_unknown",
            0,
        ),
        (
            ProviderError(
                provider="dashscope",
                operation="image_generate",
                code="provider_http_error",
                message="provider unavailable",
                status_code=503,
            ),
            "submitted_unknown",
            0,
        ),
    ],
)
async def test_worker_distinguishes_known_failure_from_uncertain_submission(
    error: Exception,
    expected_status: str,
    expected_releases: int,
) -> None:
    job = _job("image", {"prompt": "red kite"})
    job = GenerationRecord(
        **{
            **{field: getattr(job, field) for field in job.__dataclass_fields__},
            "status": "accepted",
        }
    )
    repository = _Repository(job)
    billing = _Billing()
    worker = DurableGenerationWorker(
        cast(Any, repository),
        WorkerDependencies(
            provider_resolver=_Resolver(),
            artifact_storage=_Storage(),
            billing=billing,
            executor=_FailingExecutor(error),
            heartbeat=_NoopHeartbeat(),
            concurrency=_PermitSemaphore(),
        ),
    )
    event = OutboxRecord(
        event_id=uuid4(),
        tenant_id=job.tenant_id,
        aggregate_type="generation_job",
        aggregate_id=job.db_id,
        event_type="generation.accepted",
        aggregate_version=1,
        payload={"job_id": str(job.job_id)},
        attempts=1,
    )

    with pytest.raises(GenerationInfrastructureError):
        await worker.process(event)

    assert repository.job.status == expected_status
    assert len(billing.releases) == expected_releases
