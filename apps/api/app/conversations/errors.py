"""Public-safe errors for the durable conversation boundary."""

from __future__ import annotations

from app.auth.errors import AuthError


class ConversationError(AuthError):
    """A conversation error safe to map through the public error handler."""


class ConversationNotFoundError(ConversationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="CONVERSATION_NOT_FOUND",
            message="对话不存在",
        )


class ModelNotFoundError(ConversationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="MODEL_NOT_FOUND",
            message="所选模型不存在或无权使用",
        )


class ModelUnavailableError(ConversationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="CONVERSATION_UNAVAILABLE",
            message="对话处理服务暂时不可用",
            retryable=True,
        )


class ConversationBusyError(ConversationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="CONVERSATION_BUSY",
            message="对话已有请求正在处理中",
            retryable=True,
        )


class MessageNotLatestError(ConversationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="MESSAGE_NOT_LATEST",
            message="只能重新生成最后一条助手消息",
        )


class IdempotencyConflictError(ConversationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message="client_request_id 已用于其他请求",
        )


class IdempotencyInProgressError(ConversationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="IDEMPOTENCY_IN_PROGRESS",
            message="相同请求正在处理中，请稍后查询",
            retryable=True,
        )


class ChatSubmissionDisabledError(ConversationError):
    """The API must fail before any durable row is written."""

    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="CHAT_SUBMISSION_DISABLED",
            message="聊天处理基础设施尚未配置",
            retryable=True,
        )


class StreamCursorError(ConversationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=400,
            code="STREAM_CURSOR_INVALID",
            message="流恢复游标无效",
        )


class StreamCapacityError(ConversationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=429,
            code="STREAM_CAPACITY_EXCEEDED",
            message="实时连接数已达上限，请稍后重试",
            retryable=True,
            details={"retry_after_seconds": 2},
        )


class ConversationInfrastructureError(ConversationError):
    """A safe operational error; diagnostics remain server-side."""

    def __init__(self, code: str = "CONVERSATION_UNAVAILABLE") -> None:
        super().__init__(
            status_code=503,
            code=code,
            message="对话处理服务暂时不可用",
            retryable=True,
        )


__all__ = [
    "ChatSubmissionDisabledError",
    "ConversationBusyError",
    "ConversationError",
    "ConversationInfrastructureError",
    "ConversationNotFoundError",
    "IdempotencyConflictError",
    "IdempotencyInProgressError",
    "MessageNotLatestError",
    "ModelNotFoundError",
    "ModelUnavailableError",
    "StreamCapacityError",
    "StreamCursorError",
]
