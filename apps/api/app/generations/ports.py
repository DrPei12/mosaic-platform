"""Durability ports for generation workers.

These are intentionally interfaces only.  A deployment without a durable
queue, object store, and billing adapter must stop with a configuration error;
it must not silently run an in-process coroutine or report a remote URL as a
successful product artifact.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from app.billing.ports import BillingSettlementPort
from app.providers.ports import (
    AudioGenerationPort,
    ImageGenerationPort,
    TextGenerationPort,
    VideoGenerationPort,
)

if TYPE_CHECKING:
    from app.generations.repository import GenerationRecord


@dataclass(frozen=True, slots=True)
class AudioVoiceBinding:
    """Trusted, tenant-scoped voice selected by the server-side route."""

    target_model: str
    provider_voice_id: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProviderPorts:
    text: TextGenerationPort | None = None
    image: ImageGenerationPort | None = None
    video: VideoGenerationPort | None = None
    audio: AudioGenerationPort | None = None
    # The provider model id is loaded from the trusted deployment catalog.  It
    # is deliberately not part of the public generation request.
    provider_model_id: str | None = None
    provider_name: str | None = None
    audio_voice: AudioVoiceBinding | None = None


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Internal storage result.  ``object_key`` must never be public API data."""

    storage_provider: str
    object_key: str
    mime_type: str
    size_bytes: int
    sha256: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GenerationArtifactInput:
    """A downloaded artifact ready for one short persistence transaction."""

    kind: str
    stored: StoredArtifact


@dataclass(frozen=True, slots=True)
class GenerationUsage:
    """Normalized provider usage persisted with a generation job."""

    input_tokens: int = 0
    output_tokens: int = 0
    image_count: int = 0
    video_seconds: int = 0
    audio_seconds: int = 0
    character_count: int = 0
    audio_duration_ms: int = 0
    video_duration_ms: int = 0
    storage_bytes: int = 0
    billable_units: int = 0

    def __post_init__(self) -> None:
        values = (
            self.input_tokens,
            self.output_tokens,
            self.image_count,
            self.video_seconds,
            self.audio_seconds,
            self.character_count,
            self.audio_duration_ms,
            self.video_duration_ms,
            self.storage_bytes,
            self.billable_units,
        )
        if any(isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("generation usage values must be non-negative integers")
        if any(not isinstance(value, int) for value in values):
            raise TypeError("generation usage values must be integers")


@dataclass(frozen=True, slots=True)
class GenerationExecutionResult:
    """Provider result plus locally stored artifacts and normalized usage."""

    artifacts: tuple[GenerationArtifactInput, ...] = ()
    provider_request_id: str | None = None
    provider_task_id: str | None = None
    usage: GenerationUsage = field(default_factory=GenerationUsage)


class ArtifactStoragePort(Protocol):
    storage_provider: str

    async def transfer_remote(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        remote_url: str,
        kind: str,
        mime_type: str,
    ) -> StoredArtifact: ...

    async def open_stream(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        object_key: str,
    ) -> AsyncIterator[bytes]: ...

    async def put_bytes(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        content: bytes,
        kind: str,
        mime_type: str,
    ) -> StoredArtifact: ...

    async def delete_object(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        object_key: str,
    ) -> None: ...


class OutboxRelayPort(Protocol):
    async def publish(self, event: object) -> None: ...


class ProviderResolverPort(Protocol):
    async def resolve(self, *, deployment_id: UUID, tenant_id: UUID) -> ProviderPorts: ...


class GenerationExecutorPort(Protocol):
    """Worker-owned provider invocation and storage-transfer boundary."""

    async def execute(
        self,
        *,
        job: GenerationRecord,
        providers: ProviderPorts,
        artifact_storage: ArtifactStoragePort,
        billing: BillingSettlementPort,
        submission_recorder: GenerationSubmissionRecorderPort | None = None,
    ) -> GenerationExecutionResult: ...


class GenerationSubmissionRecorderPort(Protocol):
    async def record_provider_request(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        provider_request_id: str,
        lease_token: UUID,
        fencing_token: int,
    ) -> None: ...

    async def record_provider_task(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        provider_task_id: str,
        lease_token: UUID,
        fencing_token: int,
    ) -> None: ...


class GenerationHeartbeatPort(Protocol):
    """Fenced liveness check required before and during provider work."""

    async def ensure_live(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        fencing_token: int,
        phase: str,
    ) -> None: ...


__all__ = [
    "ArtifactStoragePort",
    "AudioVoiceBinding",
    "BillingSettlementPort",
    "GenerationArtifactInput",
    "GenerationExecutionResult",
    "GenerationExecutorPort",
    "GenerationHeartbeatPort",
    "GenerationSubmissionRecorderPort",
    "GenerationUsage",
    "OutboxRelayPort",
    "ProviderPorts",
    "ProviderResolverPort",
    "StoredArtifact",
]
