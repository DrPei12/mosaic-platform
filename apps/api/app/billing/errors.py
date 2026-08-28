"""Stable, non-sensitive domain errors for wallet operations."""

from __future__ import annotations

from typing import Final


class BillingError(RuntimeError):
    """Base error that an HTTP adapter can map without exposing SQL details."""

    status_code: int = 500
    retryable: bool = False

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable


class BillingInputError(BillingError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(code=code, message=message, status_code=400)


class BillingNotFound(BillingError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(code=code, message=message, status_code=404)


class BillingConflict(BillingError):
    def __init__(self, *, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(code=code, message=message, status_code=409, retryable=retryable)


class BillingStorageError(BillingError):
    """A database failure mapped to a safe retryable response."""

    def __init__(self) -> None:
        super().__init__(
            code="BILLING_UNAVAILABLE",
            message="账务服务暂时不可用",
            status_code=503,
            retryable=True,
        )


class BillingInvariantError(BillingError):
    """A persisted wallet state violated a financial invariant."""

    def __init__(self) -> None:
        super().__init__(
            code="BILLING_INVARIANT_VIOLATION",
            message="账务状态异常",
            status_code=500,
            retryable=False,
        )


INSUFFICIENT_FUNDS: Final = "BILLING_INSUFFICIENT_FUNDS"
RESERVATION_NOT_FOUND: Final = "BILLING_RESERVATION_NOT_FOUND"
WALLET_NOT_FOUND: Final = "BILLING_WALLET_NOT_FOUND"
WALLET_UNAVAILABLE: Final = "BILLING_WALLET_UNAVAILABLE"
RESERVATION_IDEMPOTENCY_CONFLICT: Final = "BILLING_RESERVATION_IDEMPOTENCY_CONFLICT"
CAPTURE_AMOUNT_EXCEEDED: Final = "BILLING_CAPTURE_AMOUNT_EXCEEDED"
CAPTURE_CONFLICT: Final = "BILLING_CAPTURE_CONFLICT"
RELEASE_CONFLICT: Final = "BILLING_RELEASE_CONFLICT"
RESERVATION_EXPIRED: Final = "BILLING_RESERVATION_EXPIRED"
CURRENCY_MISMATCH: Final = "BILLING_CURRENCY_MISMATCH"


__all__ = [
    "CAPTURE_AMOUNT_EXCEEDED",
    "CAPTURE_CONFLICT",
    "CURRENCY_MISMATCH",
    "INSUFFICIENT_FUNDS",
    "RELEASE_CONFLICT",
    "RESERVATION_EXPIRED",
    "RESERVATION_IDEMPOTENCY_CONFLICT",
    "RESERVATION_NOT_FOUND",
    "WALLET_NOT_FOUND",
    "WALLET_UNAVAILABLE",
    "BillingConflict",
    "BillingError",
    "BillingInputError",
    "BillingInvariantError",
    "BillingNotFound",
    "BillingStorageError",
]
