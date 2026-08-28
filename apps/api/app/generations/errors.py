"""Stable public and internal errors for the generation job boundary."""

from __future__ import annotations

from typing import Any

from app.auth.errors import AuthError


class GenerationError(AuthError):
    """An error that is safe to map through the existing public error handler."""


class ModelUnavailableError(GenerationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="MODEL_UNAVAILABLE",
            message="所选模型当前不可用",
            retryable=True,
        )


class IdempotencyConflictError(GenerationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message="client_request_id 已用于其他请求",
            retryable=False,
        )


class IdempotencyInProgressError(GenerationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="IDEMPOTENCY_IN_PROGRESS",
            message="相同请求正在处理中，请稍后查询任务",
            retryable=True,
        )


class GenerationNotFoundError(GenerationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=404,
            code="GENERATION_NOT_FOUND",
            message="生成任务不存在",
            retryable=False,
        )


class GenerationStateConflictError(GenerationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="GENERATION_STATE_CONFLICT",
            message="生成任务状态已被其他工作进程更新",
            retryable=True,
        )


class GenerationInfrastructureError(GenerationError):
    diagnostic_details: dict[str, Any] | None

    def __init__(self, code: str, *, details: dict[str, Any] | None = None) -> None:
        self.diagnostic_details = details
        super().__init__(
            status_code=503,
            code=code,
            message="生成任务处理基础设施尚未配置",
            retryable=True,
            # Internal dependency names must not cross the public error
            # boundary.  Observability code may use diagnostic_details.
            details=None,
        )


__all__ = [
    "GenerationError",
    "GenerationInfrastructureError",
    "GenerationNotFoundError",
    "GenerationStateConflictError",
    "IdempotencyConflictError",
    "IdempotencyInProgressError",
    "ModelUnavailableError",
]
