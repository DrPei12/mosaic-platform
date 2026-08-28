"""Real provider execution for image, video, audio, and text generation."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.billing.ports import BillingSettlementPort
from app.generations.errors import GenerationInfrastructureError
from app.generations.ports import (
    ArtifactStoragePort,
    GenerationArtifactInput,
    GenerationExecutionResult,
    GenerationSubmissionRecorderPort,
    GenerationUsage,
    ProviderPorts,
)
from app.generations.repository import GenerationRecord
from app.providers.ports import (
    AudioGenerationRequest,
    ChatMessage,
    ImageGenerationRequest,
    TextCompletionRequest,
    VideoGenerationRequest,
    VideoTaskStatus,
)


class DashScopeGenerationExecutor:
    """Invoke the already configured DashScope adapter exactly once per job."""

    def __init__(self, *, max_inline_artifact_bytes: int = 200 * 1024 * 1024) -> None:
        if max_inline_artifact_bytes < 1:
            raise ValueError("max_inline_artifact_bytes must be positive")
        self._max_inline_artifact_bytes = max_inline_artifact_bytes

    async def execute(
        self,
        *,
        job: GenerationRecord,
        providers: ProviderPorts,
        artifact_storage: ArtifactStoragePort,
        billing: BillingSettlementPort,
        submission_recorder: GenerationSubmissionRecorderPort | None = None,
    ) -> GenerationExecutionResult:
        del billing
        values = _input_values(job.request_payload)
        model = providers.provider_model_id or job.product_model_id
        if not model.strip():
            raise GenerationInfrastructureError("GENERATION_PROVIDER_MODEL_UNAVAILABLE")
        if job.modality == "image":
            return await self._image(
                job=job,
                providers=providers,
                storage=artifact_storage,
                model=model,
                values=values,
                submission_recorder=submission_recorder,
            )
        if job.modality == "video":
            return await self._video(
                job=job,
                providers=providers,
                storage=artifact_storage,
                model=model,
                values=values,
                submission_recorder=submission_recorder,
            )
        if job.modality == "audio":
            return await self._audio(
                job=job,
                providers=providers,
                storage=artifact_storage,
                model=model,
                values=values,
                submission_recorder=submission_recorder,
            )
        if job.modality == "text":
            return await self._text(
                providers=providers,
                model=model,
                values=values,
                job=job,
                submission_recorder=submission_recorder,
            )
        raise GenerationInfrastructureError("GENERATION_MODALITY_UNSUPPORTED")

    async def recover_video(
        self,
        *,
        job: GenerationRecord,
        providers: ProviderPorts,
        artifact_storage: ArtifactStoragePort,
    ) -> GenerationExecutionResult | None:
        if job.modality != "video" or job.provider_task_id is None:
            raise GenerationInfrastructureError("GENERATION_RECONCILIATION_UNSUPPORTED")
        provider = providers.video
        if provider is None:
            raise GenerationInfrastructureError("GENERATION_PROVIDER_NOT_CONFIGURED")
        result = await provider.get_video_task(job.provider_task_id)
        if result.status in {VideoTaskStatus.PENDING, VideoTaskStatus.RUNNING}:
            return None
        if result.status is not VideoTaskStatus.SUCCEEDED or result.video is None:
            raise GenerationInfrastructureError("GENERATION_PROVIDER_TASK_FAILED")
        artifact = await artifact_storage.transfer_remote(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            remote_url=result.video.url,
            kind="output",
            mime_type="video/mp4",
        )
        values = _input_values(job.request_payload)
        requested_duration = _bounded_int(
            values.get("duration_seconds"),
            default=2,
            minimum=2,
            maximum=15,
        )
        usage = result.usage
        duration = (
            usage.duration_seconds
            if usage and usage.duration_seconds is not None
            else requested_duration
        )
        count = usage.video_count if usage and usage.video_count is not None else 1
        return GenerationExecutionResult(
            artifacts=(GenerationArtifactInput(kind="output", stored=artifact),),
            provider_request_id=result.request_id,
            provider_task_id=job.provider_task_id,
            usage=GenerationUsage(
                video_seconds=max(int(duration), 0),
                video_duration_ms=max(int(duration), 0) * 1000,
                storage_bytes=artifact.size_bytes,
                billable_units=max(int(duration), 0) * max(count, 1),
            ),
        )

    async def _image(
        self,
        *,
        job: GenerationRecord,
        providers: ProviderPorts,
        storage: ArtifactStoragePort,
        model: str,
        values: Mapping[str, Any],
        submission_recorder: GenerationSubmissionRecorderPort | None,
    ) -> GenerationExecutionResult:
        provider = providers.image
        if provider is None:
            raise GenerationInfrastructureError("GENERATION_PROVIDER_NOT_CONFIGURED")
        prompt = _required_string(values.get("prompt"), "prompt")
        request = ImageGenerationRequest(
            model=model,
            prompt=prompt,
            size=_string_or_default(values.get("size"), "512*512"),
            count=_bounded_int(values.get("count"), default=1, minimum=1, maximum=6),
        )
        result = await provider.generate(request)
        await _record_provider_request(
            submission_recorder,
            job=job,
            provider_request_id=result.request_id,
        )
        stored: list[GenerationArtifactInput] = []
        for image in result.images:
            if image.remote is not None:
                artifact = await storage.transfer_remote(
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    remote_url=image.remote.url,
                    kind="output",
                    mime_type="image/png",
                )
            else:
                if image.data_base64 is None:
                    raise GenerationInfrastructureError("GENERATION_PROVIDER_PROTOCOL_ERROR")
                content = _decode_base64(image.data_base64, self._max_inline_artifact_bytes)
                artifact = await storage.put_bytes(
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    content=content,
                    kind="output",
                    mime_type="image/png",
                )
            stored.append(GenerationArtifactInput(kind="output", stored=artifact))
        usage_count = result.usage.image_count if result.usage is not None else len(stored)
        return GenerationExecutionResult(
            artifacts=tuple(stored),
            provider_request_id=result.request_id,
            usage=GenerationUsage(
                image_count=max(usage_count, len(stored)),
                storage_bytes=sum(item.stored.size_bytes for item in stored),
                billable_units=max(usage_count, len(stored)),
            ),
        )

    async def _video(
        self,
        *,
        job: GenerationRecord,
        providers: ProviderPorts,
        storage: ArtifactStoragePort,
        model: str,
        values: Mapping[str, Any],
        submission_recorder: GenerationSubmissionRecorderPort | None,
    ) -> GenerationExecutionResult:
        provider = providers.video
        if provider is None:
            raise GenerationInfrastructureError("GENERATION_PROVIDER_NOT_CONFIGURED")
        if submission_recorder is None:
            raise GenerationInfrastructureError("GENERATION_SUBMISSION_RECORDER_UNAVAILABLE")
        prompt = _required_string(values.get("prompt"), "prompt")
        request = VideoGenerationRequest(
            model=model,
            prompt=prompt,
            resolution=_string_or_default(values.get("resolution"), "720P"),
            ratio=_string_or_default(values.get("ratio"), "16:9"),
            duration_seconds=_bounded_int(
                values.get("duration_seconds"),
                default=2,
                minimum=2,
                maximum=15,
            ),
        )
        task_id = await provider.submit_video(request)
        try:
            lease_token, fencing_token = _job_fence(job)
            await submission_recorder.record_provider_task(
                tenant_id=job.tenant_id,
                job_id=job.job_id,
                provider_task_id=task_id,
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
        except Exception as exc:
            raise GenerationInfrastructureError(
                "GENERATION_SUBMISSION_PERSISTENCE_UNKNOWN"
            ) from exc
        result = await provider.wait_for_video(task_id)
        if result.status is not VideoTaskStatus.SUCCEEDED or result.video is None:
            raise GenerationInfrastructureError("GENERATION_PROVIDER_TASK_FAILED")
        await _record_provider_request(
            submission_recorder,
            job=job,
            provider_request_id=result.request_id,
        )
        artifact = await storage.transfer_remote(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            remote_url=result.video.url,
            kind="output",
            mime_type="video/mp4",
        )
        usage = result.usage
        duration = usage.duration_seconds if usage and usage.duration_seconds is not None else request.duration_seconds
        count = usage.video_count if usage and usage.video_count is not None else 1
        return GenerationExecutionResult(
            artifacts=(GenerationArtifactInput(kind="output", stored=artifact),),
            provider_request_id=result.request_id,
            provider_task_id=task_id,
            usage=GenerationUsage(
                video_seconds=max(int(duration), 0),
                video_duration_ms=max(int(duration), 0) * 1000,
                storage_bytes=artifact.size_bytes,
                billable_units=max(int(duration), 0) * max(count, 1),
            ),
        )

    async def _audio(
        self,
        *,
        job: GenerationRecord,
        providers: ProviderPorts,
        storage: ArtifactStoragePort,
        model: str,
        values: Mapping[str, Any],
        submission_recorder: GenerationSubmissionRecorderPort | None,
    ) -> GenerationExecutionResult:
        provider = providers.audio
        if provider is None:
            raise GenerationInfrastructureError("GENERATION_PROVIDER_NOT_CONFIGURED")
        voice_binding = providers.audio_voice
        if voice_binding is None or voice_binding.target_model != model:
            raise GenerationInfrastructureError("GENERATION_PROVIDER_ROUTE_UNAVAILABLE")
        text = _required_string(values.get("text"), "text")
        request = AudioGenerationRequest(
            model=model,
            text=text,
            voice=voice_binding.provider_voice_id,
            language_type=_string_or_default(values.get("language_type"), "Chinese"),
        )
        result = await provider.synthesize(request)
        await _record_provider_request(
            submission_recorder,
            job=job,
            provider_request_id=result.request_id,
        )
        artifact = await storage.transfer_remote(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            remote_url=result.audio.url,
            kind="output",
            mime_type="audio/wav",
        )
        characters = result.usage.characters if result.usage is not None else len(text)
        return GenerationExecutionResult(
            artifacts=(GenerationArtifactInput(kind="output", stored=artifact),),
            provider_request_id=result.request_id,
            usage=GenerationUsage(
                character_count=max(characters, len(text)),
                storage_bytes=artifact.size_bytes,
                billable_units=max(characters, len(text)),
            ),
        )

    async def _text(
        self,
        *,
        job: GenerationRecord,
        providers: ProviderPorts,
        model: str,
        values: Mapping[str, Any],
        submission_recorder: GenerationSubmissionRecorderPort | None,
    ) -> GenerationExecutionResult:
        provider = providers.text
        if provider is None:
            raise GenerationInfrastructureError("GENERATION_PROVIDER_NOT_CONFIGURED")
        messages_value = values.get("messages")
        messages: list[ChatMessage] = []
        if isinstance(messages_value, list):
            for item in messages_value:
                if not isinstance(item, Mapping):
                    raise TypeError("invalid generation message")
                messages.append(
                    ChatMessage(
                        role=str(item.get("role", "user")),  # type: ignore[arg-type]
                        content=_required_string(item.get("content"), "message content"),
                    )
                )
        if not messages:
            messages = [ChatMessage(role="user", content=_required_string(values.get("prompt"), "prompt"))]
        result = await provider.complete(
            TextCompletionRequest(model=model, messages=tuple(messages))
        )
        await _record_provider_request(
            submission_recorder,
            job=job,
            provider_request_id=result.request_id,
        )
        usage = result.usage
        return GenerationExecutionResult(
            provider_request_id=result.request_id,
            usage=GenerationUsage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                billable_units=usage.total_tokens if usage else 0,
            ),
        )


def _input_values(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("input")
    if not isinstance(value, Mapping):
        raise TypeError("generation input is invalid")
    return value


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value


def _string_or_default(value: object, default: str) -> str:
    return value if isinstance(value, str) and value.strip() else default


def _bounded_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError("generation integer parameter is out of range")
    return value


def _decode_base64(value: str, maximum: int) -> bytes:
    try:
        content = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise GenerationInfrastructureError("GENERATION_PROVIDER_PROTOCOL_ERROR") from exc
    if len(content) > maximum:
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_TOO_LARGE")
    return content


async def _record_provider_request(
    recorder: GenerationSubmissionRecorderPort | None,
    *,
    job: GenerationRecord,
    provider_request_id: str | None,
) -> None:
    if recorder is None or provider_request_id is None:
        return
    try:
        lease_token, fencing_token = _job_fence(job)
        await recorder.record_provider_request(
            tenant_id=job.tenant_id,
            job_id=job.job_id,
            provider_request_id=provider_request_id,
            lease_token=lease_token,
            fencing_token=fencing_token,
        )
    except Exception as exc:
        raise GenerationInfrastructureError(
            "GENERATION_SUBMISSION_PERSISTENCE_UNKNOWN"
        ) from exc


def _job_fence(job: GenerationRecord) -> tuple[UUID, int]:
    if job.lease_token is None or job.fencing_token < 1:
        raise GenerationInfrastructureError("GENERATION_FENCE_MISSING")
    return job.lease_token, job.fencing_token


__all__ = ["DashScopeGenerationExecutor"]
