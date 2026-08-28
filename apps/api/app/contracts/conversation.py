from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.errors import ErrorBody

NonEmptyId = Annotated[str, Field(min_length=1, max_length=200)]


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: NonEmptyId
    role: Literal["user", "assistant"]
    content: str = Field(max_length=1_000_000)
    status: Literal["streaming", "complete", "stopped", "failed"]
    created_at: datetime
    request_id: NonEmptyId | None = None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: NonEmptyId
    product_model_id: NonEmptyId
    title: str = Field(min_length=1, max_length=240)
    messages: list[ConversationMessage] = Field(max_length=20_000)
    updated_at: datetime
    active_request_id: NonEmptyId | None
    active_request_cursor: int | None = Field(default=None, ge=-1)

    @model_validator(mode="after")
    def validate_active_cursor(self) -> Self:
        if (self.active_request_id is None) != (self.active_request_cursor is None):
            raise ValueError("active_request_id and active_request_cursor must be set together")
        return self


class ConversationSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: NonEmptyId
    product_model_id: NonEmptyId
    title: str = Field(min_length=1, max_length=240)
    preview: str = Field(max_length=1000)
    updated_at: datetime


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_model_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9-]+$")
    client_request_id: NonEmptyId


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=64_000)
    client_request_id: NonEmptyId

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class RegenerateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: NonEmptyId


class ResumeConversationRequest(BaseModel):
    """Optional durable cursor supplied when replaying a chat SSE stream.

    ``last_event_id`` accepts the standard SSE ``Last-Event-ID`` spelling as
    an input alias; the canonical Python/JSON field remains snake_case.
    Supplying both forms is allowed only when they identify the same event.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    cursor: int | None = Field(default=None, ge=-1)
    last_event_id: int | None = Field(
        default=None,
        ge=0,
        alias="Last-Event-ID",
    )

    @model_validator(mode="after")
    def validate_cursor_consistency(self) -> Self:
        if (
            self.cursor is not None
            and self.last_event_id is not None
            and self.cursor != self.last_event_id
        ):
            raise ValueError("cursor and Last-Event-ID must identify the same event")
        return self

class StreamEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: NonEmptyId
    conversation_id: NonEmptyId
    message_id: NonEmptyId


class StreamStartedEvent(StreamEventBase):
    type: Literal["started"] = "started"
    sequence: Literal[0] = 0


class StreamDeltaEvent(StreamEventBase):
    type: Literal["delta"] = "delta"
    sequence: int = Field(ge=0)
    delta: str = Field(min_length=1, max_length=64_000)


class StreamCompletedEvent(StreamEventBase):
    type: Literal["completed"] = "completed"
    sequence: int = Field(ge=0)
    content: str = Field(max_length=1_000_000)


class StreamStoppedEvent(StreamEventBase):
    type: Literal["stopped"] = "stopped"
    sequence: int = Field(ge=0)


class StreamFailedEvent(StreamEventBase):
    type: Literal["failed"] = "failed"
    sequence: int = Field(ge=0)
    error: ErrorBody


ChatStreamEvent = Annotated[
    StreamStartedEvent
    | StreamDeltaEvent
    | StreamCompletedEvent
    | StreamStoppedEvent
    | StreamFailedEvent,
    Field(discriminator="type"),
]
