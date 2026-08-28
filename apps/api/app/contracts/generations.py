"""Public contracts for durable, asynchronous generation jobs.

The request deliberately has one small, strict input envelope for all four
modalities.  Provider-specific identifiers and storage locations are never a
part of this contract; routing is resolved from the tenant's server-side
catalog entitlement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GenerationModality = Literal["text", "image", "video", "audio"]
GenerationStatus = Literal[
    "accepted",
    "reserved",
    "submitted",
    "submitted_unknown",
    "queued",
    "running",
    "storing",
    "succeeded",
    "failed",
    "cancelled",
    "expired",
]

NonEmptyId = Annotated[str, Field(min_length=1, max_length=255)]


class GenerationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=8_000)


class GenerationInput(BaseModel):
    """Provider-neutral input fields.

    Only fields relevant to the selected modality are consumed by the
    application service.  Keeping the envelope strict prevents accidental
    provider parameters from becoming part of the public API.
    """

    model_config = ConfigDict(extra="forbid")

    messages: list[GenerationMessage] | None = Field(default=None, max_length=128)
    prompt: str | None = Field(default=None, min_length=1, max_length=16_000)
    text: str | None = Field(default=None, min_length=1, max_length=8_000)
    language_type: str | None = Field(default=None, min_length=1, max_length=64)
    size: str = Field(default="512*512", pattern=r"^[0-9]{3,4}\*[0-9]{3,4}$")
    count: int = Field(default=1, ge=1, le=6)
    resolution: Literal["720P", "1080P"] = "720P"
    ratio: Literal["1:1", "16:9", "9:16", "4:3", "3:4"] = "16:9"
    duration_seconds: int = Field(default=2, ge=2, le=15)


class CreateGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_model_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,159}$")
    modality: GenerationModality
    input: GenerationInput
    client_request_id: NonEmptyId

    @field_validator("client_request_id")
    @classmethod
    def validate_client_request_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("client_request_id must not be blank")
        return value

    @model_validator(mode="after")
    def validate_modality_input(self) -> CreateGenerationRequest:
        values = self.input
        if self.modality == "text":
            if not values.messages and not values.prompt:
                raise ValueError("text generation requires messages or prompt")
        elif self.modality in {"image", "video"}:
            if not values.prompt:
                raise ValueError(f"{self.modality} generation requires prompt")
        elif self.modality == "audio" and not values.text:
            raise ValueError("audio generation requires text")
        return self


class GenerationArtifactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: NonEmptyId
    kind: Literal["input", "output", "thumbnail", "preview"]
    status: Literal["pending", "ready", "expired", "deleted"]
    mime_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0)


class GenerationJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: NonEmptyId
    product_model_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,159}$")
    modality: GenerationModality
    status: GenerationStatus
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Z0-9_]+$",
    )
    reconciliation_pending: bool = False
    artifacts: list[GenerationArtifactResponse] = Field(default_factory=list, max_length=64)


__all__ = [
    "CreateGenerationRequest",
    "GenerationArtifactResponse",
    "GenerationInput",
    "GenerationJobResponse",
    "GenerationMessage",
    "GenerationModality",
    "GenerationStatus",
]
