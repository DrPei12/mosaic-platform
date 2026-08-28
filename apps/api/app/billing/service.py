"""PostgreSQL wallet reservation and append-only ledger service."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import (
    CAPTURE_AMOUNT_EXCEEDED,
    CAPTURE_CONFLICT,
    CURRENCY_MISMATCH,
    INSUFFICIENT_FUNDS,
    RELEASE_CONFLICT,
    RESERVATION_EXPIRED,
    RESERVATION_IDEMPOTENCY_CONFLICT,
    RESERVATION_NOT_FOUND,
    WALLET_NOT_FOUND,
    WALLET_UNAVAILABLE,
    BillingConflict,
    BillingError,
    BillingInputError,
    BillingInvariantError,
    BillingNotFound,
    BillingStorageError,
)
from app.billing.ports import (
    BillingPort,
    BillingUsage,
    CaptureResult,
    Money,
    PriceSnapshot,
    ReleaseResult,
    ReservationResult,
)
from app.billing.pricing import charge_for_usage, pricing_version, reservation_amount
from app.billing.queries import (
    reservation_by_id_for_update,
    reservation_by_source,
    reservation_wallet_id,
    wallet_by_currency_for_update,
    wallet_by_id_for_update,
)
from app.billing.state import (
    InvalidReservationTransition,
    ReservationStatus,
    decide_capture,
    decide_release,
    reservation_is_expired,
)
from app.infrastructure.models import (
    BalanceReservations,
    GenerationJobs,
    InferenceRequests,
    LedgerEntries,
    PriceVersions,
    UsageRecords,
    WalletAccounts,
)
from app.observability.metrics import record_billing_invariant, record_billing_operation

_SOURCE_TYPE = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,63}$")
_RESERVATION_STATUSES = frozenset({"pending", "committed", "released", "expired"})


class SqlAlchemyBillingService(BillingPort):
    """Owns one short PostgreSQL transaction per financial operation.

    No provider, Redis call, or object-storage call belongs inside these
    transactions.  Admission can join a caller-owned request transaction;
    worker capture/release operations use separate short transactions after
    provider work has finished.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reserve(
        self,
        *,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        amount: Money,
        expires_at: datetime,
    ) -> ReservationResult:
        amount = _require_money(amount)
        _require_positive_reservation_amount(amount)
        normalized_source = _normalize_source_type(source_type)
        _require_uuid(tenant_id, "tenant_id")
        _require_uuid(source_id, "source_id")
        expires_at = _require_future_utc(expires_at)

        try:
            async with self._session.begin():
                return await self._reserve_in_transaction(
                    tenant_id=tenant_id,
                    source_type=normalized_source,
                    source_id=source_id,
                    amount=amount,
                    expires_at=expires_at,
                )
        except BillingError as exc:
            _record_billing_error(exc)
            raise
        except IntegrityError as exc:
            if _is_unique_violation(exc):
                return await self._resolve_reservation_race(
                    tenant_id=tenant_id,
                    source_type=normalized_source,
                    source_id=source_id,
                    amount=amount,
                    expires_at=expires_at,
                )
            raise BillingStorageError from exc
        except SQLAlchemyError as exc:
            raise BillingStorageError from exc

    async def reserve_in_transaction(
        self,
        *,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        price: PriceSnapshot,
        expires_at: datetime,
    ) -> ReservationResult:
        """Create the hold inside the caller's existing acceptance transaction.

        This method deliberately does not call ``begin`` or commit.  The
        caller owns the transaction that also contains the idempotency row,
        request/job, accepted catalog snapshot, and outbox event.
        """

        amount = reservation_amount(price)
        normalized_source = _normalize_source_type(source_type)
        _require_uuid(tenant_id, "tenant_id")
        _require_uuid(source_id, "source_id")
        expires_at = _require_future_utc(expires_at)
        try:
            return await self._reserve_in_transaction(
                tenant_id=tenant_id,
                source_type=normalized_source,
                source_id=source_id,
                amount=amount,
                expires_at=expires_at,
            )
        except BillingError as exc:
            _record_billing_error(exc)
            raise
        except SQLAlchemyError as exc:
            raise BillingStorageError from exc

    async def capture(
        self,
        *,
        tenant_id: UUID,
        reservation_id: UUID,
        actual: Money | None = None,
        usage: BillingUsage | None = None,
    ) -> CaptureResult:
        if actual is not None and usage is not None:
            raise BillingInputError(
                code="BILLING_CAPTURE_INPUT_CONFLICT",
                message="结算不能同时提供金额和 usage",
            )
        _require_uuid(tenant_id, "tenant_id")
        _require_uuid(reservation_id, "reservation_id")

        try:
            async with self._session.begin():
                wallet_id = await self._reservation_wallet_id(tenant_id, reservation_id)
                wallet = await self._lock_wallet_by_id(tenant_id, wallet_id)
                reservation = await self._lock_reservation(tenant_id, reservation_id)
                _assert_wallet_reservation_match(wallet, reservation)
                usage_record: UsageRecords | None = None
                price: PriceSnapshot | None = None
                if usage is not None or actual is None:
                    price = await self._price_for_reservation(tenant_id, reservation)
                    usage_record = await self._usage_for_reservation(tenant_id, reservation)
                    if usage is None:
                        usage = _billing_usage_from_record(usage_record)
                    actual = charge_for_usage(price, usage)
                assert actual is not None
                _assert_currency(actual, wallet.currency)
                if (
                    reservation.status == "pending"
                    and reservation_is_expired(
                        expires_at=_as_utc(reservation.expires_at),
                        now=datetime.now(UTC),
                    )
                ):
                    # Never charge an expired hold. A reconciliation worker or
                    # explicit release must free the reserved projection; that
                    # follow-up remains a separate short transaction.
                    raise BillingConflict(
                        code=RESERVATION_EXPIRED,
                        message="该预留已过期",
                    )

                try:
                    decision = decide_capture(
                        status=reservation.status,
                        reserved_minor=int(reservation.amount_minor),
                        actual_minor=actual.amount_minor,
                        captured_minor=(
                            int(reservation.captured_amount_minor)
                            if reservation.captured_amount_minor is not None
                            else None
                        ),
                    )
                except InvalidReservationTransition as exc:
                    raise _capture_transition_error(reservation.status, actual, reservation) from exc
                except ValueError as exc:
                    raise BillingInvariantError from exc

                if decision.idempotent:
                    # Terminal capture is immutable.  Replaying the exact
                    # amount returns the original result without new journal
                    # rows or wallet mutations.
                    if usage_record is not None and price is not None:
                        _apply_usage_charge(
                            usage_record,
                            price=price,
                            charge=actual,
                        )
                    result = _capture_result(
                        reservation=reservation,
                        charged_minor=decision.charged_minor,
                        released_minor=decision.released_minor,
                        idempotent=True,
                    )
                    record_billing_operation(operation="capture")
                    return result

                if wallet.status != "active":
                    raise BillingConflict(code=WALLET_UNAVAILABLE, message="钱包当前不可用")
                if (
                    int(wallet.reserved_minor) < int(reservation.amount_minor)
                    or int(wallet.balance_minor) < decision.charged_minor
                ):
                    raise BillingInvariantError

                wallet.reserved_minor = int(wallet.reserved_minor) - int(reservation.amount_minor)
                wallet.balance_minor = int(wallet.balance_minor) - decision.charged_minor
                wallet.version = int(wallet.version) + 1
                reservation.status = "committed"
                reservation.captured_amount_minor = decision.charged_minor
                reservation.committed_at = datetime.now(UTC)
                if usage_record is not None and price is not None:
                    _apply_usage_charge(
                        usage_record,
                        price=price,
                        charge=actual,
                    )

                if decision.charged_minor > 0:
                    self._session.add(
                        _ledger_entry(
                            tenant_id=tenant_id,
                            wallet_id=wallet.id,
                            reservation_id=reservation.id,
                            entry_type="debit",
                            amount_minor=decision.charged_minor,
                            currency=wallet.currency,
                            suffix="debit",
                        )
                    )
                if decision.released_minor > 0:
                    self._session.add(
                        _ledger_entry(
                            tenant_id=tenant_id,
                            wallet_id=wallet.id,
                            reservation_id=reservation.id,
                            entry_type="release",
                            amount_minor=decision.released_minor,
                            currency=wallet.currency,
                            suffix="release",
                        )
                    )
                await self._session.flush()
                result = _capture_result(
                    reservation=reservation,
                    charged_minor=decision.charged_minor,
                    released_minor=decision.released_minor,
                    idempotent=False,
                )
                record_billing_operation(operation="capture")
                return result
        except BillingError as exc:
            _record_billing_error(exc)
            raise
        except SQLAlchemyError as exc:
            raise BillingStorageError from exc

    async def release(
        self,
        *,
        tenant_id: UUID,
        reservation_id: UUID,
    ) -> ReleaseResult:
        _require_uuid(tenant_id, "tenant_id")
        _require_uuid(reservation_id, "reservation_id")

        try:
            async with self._session.begin():
                wallet_id = await self._reservation_wallet_id(tenant_id, reservation_id)
                wallet = await self._lock_wallet_by_id(tenant_id, wallet_id)
                reservation = await self._lock_reservation(tenant_id, reservation_id)
                _assert_wallet_reservation_match(wallet, reservation)
                try:
                    decision = decide_release(
                        status=reservation.status,
                        reserved_minor=int(reservation.amount_minor),
                    )
                except InvalidReservationTransition as exc:
                    if reservation.status in {"committed", "expired"}:
                        raise BillingConflict(
                            code=RELEASE_CONFLICT,
                            message="该预留当前不可释放",
                        ) from exc
                    raise BillingInvariantError from exc
                except ValueError as exc:
                    raise BillingInvariantError from exc

                if decision.idempotent:
                    result = _release_result(
                        reservation=reservation,
                        currency=wallet.currency,
                        released_minor=decision.released_minor,
                        idempotent=True,
                    )
                    record_billing_operation(operation="release")
                    return result

                if int(wallet.reserved_minor) < int(reservation.amount_minor):
                    raise BillingInvariantError
                wallet.reserved_minor = int(wallet.reserved_minor) - int(reservation.amount_minor)
                wallet.version = int(wallet.version) + 1
                reservation.status = "released"
                reservation.released_at = datetime.now(UTC)
                self._session.add(
                    _ledger_entry(
                        tenant_id=tenant_id,
                        wallet_id=wallet.id,
                        reservation_id=reservation.id,
                        entry_type="release",
                        amount_minor=decision.released_minor,
                        currency=wallet.currency,
                        suffix="release",
                    )
                )
                await self._session.flush()
                result = _release_result(
                    reservation=reservation,
                    currency=wallet.currency,
                    released_minor=decision.released_minor,
                    idempotent=False,
                )
                record_billing_operation(operation="release")
                return result
        except BillingError as exc:
            _record_billing_error(exc)
            raise
        except SQLAlchemyError as exc:
            raise BillingStorageError from exc

    async def _reserve_in_transaction(
        self,
        *,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        amount: Money,
        expires_at: datetime,
    ) -> ReservationResult:
        # The initial read avoids requiring a wallet in a different currency
        # just to report an idempotency conflict.  Any existing row is then
        # re-read after its wallet is locked.
        existing = await self._find_reservation_by_source(tenant_id, source_type, source_id)
        if existing is not None:
            wallet = await self._lock_wallet_by_id(tenant_id, existing.wallet_account_id)
            reservation = await self._lock_reservation(tenant_id, existing.id)
            _assert_wallet_reservation_match(wallet, reservation)
            return _resolve_existing_reservation(
                reservation=reservation,
                requested_amount=amount,
                requested_expires_at=expires_at,
            )

        wallet = await self._lock_wallet_for_currency(tenant_id, amount.currency)
        existing = await self._lock_reservation_by_source(tenant_id, source_type, source_id)
        if existing is not None:
            existing_wallet = await self._lock_wallet_by_id(tenant_id, existing.wallet_account_id)
            _assert_wallet_reservation_match(existing_wallet, existing)
            return _resolve_existing_reservation(
                reservation=existing,
                requested_amount=amount,
                requested_expires_at=expires_at,
            )

        if wallet.status != "active":
            raise BillingConflict(code=WALLET_UNAVAILABLE, message="钱包当前不可用")
        available = int(wallet.balance_minor) - int(wallet.reserved_minor)
        if available < 0:
            raise BillingInvariantError
        if amount.amount_minor > available:
            raise BillingConflict(code=INSUFFICIENT_FUNDS, message="可用余额不足")

        reservation = BalanceReservations(
            id=uuid4(),
            tenant_id=tenant_id,
            wallet_account_id=wallet.id,
            amount_minor=amount.amount_minor,
            currency=amount.currency,
            status="pending",
            source_type=source_type,
            source_id=source_id,
            expires_at=expires_at,
            captured_amount_minor=None,
        )
        wallet.reserved_minor = int(wallet.reserved_minor) + amount.amount_minor
        wallet.version = int(wallet.version) + 1
        self._session.add(reservation)
        self._session.add(
            _ledger_entry(
                tenant_id=tenant_id,
                wallet_id=wallet.id,
                reservation_id=reservation.id,
                entry_type="hold",
                amount_minor=amount.amount_minor,
                currency=wallet.currency,
                suffix="hold",
            )
        )
        await self._session.flush()
        record_billing_operation(operation="hold")
        return _reservation_result(reservation)

    async def _resolve_reservation_race(
        self,
        *,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
        amount: Money,
        expires_at: datetime,
    ) -> ReservationResult:
        """Resolve a concurrent unique-source insert without exposing SQLSTATE."""

        await self._session.rollback()
        try:
            async with self._session.begin():
                # Resolve the source row without locking first so the wallet
                # is always locked before the reservation (the same order as
                # capture/release), avoiding cross-operation deadlocks.
                reservation = await self._find_reservation_by_source(
                    tenant_id, source_type, source_id
                )
                if reservation is None:
                    raise BillingStorageError()
                wallet = await self._lock_wallet_by_id(tenant_id, reservation.wallet_account_id)
                reservation = await self._lock_reservation(tenant_id, reservation.id)
                _assert_wallet_reservation_match(wallet, reservation)
                return _resolve_existing_reservation(
                    reservation=reservation,
                    requested_amount=amount,
                    requested_expires_at=expires_at,
                )
        except BillingError:
            raise
        except SQLAlchemyError as exc:
            raise BillingStorageError from exc

    async def _find_reservation_by_source(
        self,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
    ) -> BalanceReservations | None:
        query: Select[Any] = reservation_by_source(tenant_id, source_type, source_id)
        return (await self._session.execute(query)).scalar_one_or_none()

    async def _lock_reservation_by_source(
        self,
        tenant_id: UUID,
        source_type: str,
        source_id: UUID,
    ) -> BalanceReservations | None:
        query: Select[Any] = reservation_by_source(
            tenant_id, source_type, source_id, for_update=True
        )
        return (await self._session.execute(query)).scalar_one_or_none()

    async def _reservation_wallet_id(self, tenant_id: UUID, reservation_id: UUID) -> UUID:
        query: Select[Any] = reservation_wallet_id(tenant_id, reservation_id)
        wallet_id = (await self._session.execute(query)).scalar_one_or_none()
        if wallet_id is None:
            raise BillingNotFound(code=RESERVATION_NOT_FOUND, message="预留不存在")
        return cast(UUID, wallet_id)

    async def _lock_reservation(self, tenant_id: UUID, reservation_id: UUID) -> BalanceReservations:
        query: Select[Any] = reservation_by_id_for_update(tenant_id, reservation_id)
        reservation = (await self._session.execute(query)).scalar_one_or_none()
        if reservation is None:
            raise BillingNotFound(code=RESERVATION_NOT_FOUND, message="预留不存在")
        return cast(BalanceReservations, reservation)

    async def _lock_wallet_for_currency(self, tenant_id: UUID, currency: str) -> WalletAccounts:
        query: Select[Any] = wallet_by_currency_for_update(tenant_id, currency)
        wallet = (await self._session.execute(query)).scalar_one_or_none()
        if wallet is None:
            raise BillingNotFound(code=WALLET_NOT_FOUND, message="钱包不存在")
        return cast(WalletAccounts, wallet)

    async def _lock_wallet_by_id(self, tenant_id: UUID, wallet_id: UUID) -> WalletAccounts:
        query: Select[Any] = wallet_by_id_for_update(tenant_id, wallet_id)
        wallet = (await self._session.execute(query)).scalar_one_or_none()
        if wallet is None:
            raise BillingInvariantError
        return cast(WalletAccounts, wallet)

    async def _price_for_reservation(
        self,
        tenant_id: UUID,
        reservation: BalanceReservations,
    ) -> PriceSnapshot:
        accepted_price_version_id: UUID | None
        if reservation.source_type == "chat_inference":
            accepted_price_version_id = (
                await self._session.execute(
                    select(InferenceRequests.accepted_price_version_id)
                    .where(
                        InferenceRequests.tenant_id == tenant_id,
                        InferenceRequests.id == reservation.source_id,
                    )
                )
            ).scalar_one_or_none()
        elif reservation.source_type == "generation":
            accepted_price_version_id = (
                await self._session.execute(
                    select(GenerationJobs.accepted_price_version_id)
                    .where(
                        GenerationJobs.tenant_id == tenant_id,
                        GenerationJobs.id == reservation.source_id,
                    )
                )
            ).scalar_one_or_none()
        else:
            raise BillingInvariantError
        if accepted_price_version_id is None:
            raise BillingInvariantError
        price = (
            await self._session.execute(
                select(PriceVersions).where(PriceVersions.id == accepted_price_version_id)
            )
        ).scalar_one_or_none()
        if price is None:
            raise BillingInvariantError
        return PriceSnapshot(
            price_version_id=price.id,
            price_key=price.price_key,
            version=int(price.version),
            currency=price.currency,
            unit=price.unit,
            pricing=dict(price.pricing or {}),
        )

    async def _usage_for_reservation(
        self,
        tenant_id: UUID,
        reservation: BalanceReservations,
    ) -> UsageRecords:
        if reservation.source_type == "chat_inference":
            query = select(UsageRecords).where(
                UsageRecords.tenant_id == tenant_id,
                UsageRecords.inference_request_id == reservation.source_id,
            )
        elif reservation.source_type == "generation":
            query = select(UsageRecords).where(
                UsageRecords.tenant_id == tenant_id,
                UsageRecords.generation_job_id == reservation.source_id,
            )
        else:
            raise BillingInvariantError
        usage = (await self._session.execute(query.with_for_update())).scalar_one_or_none()
        if usage is None:
            raise BillingInvariantError
        return cast(UsageRecords, usage)


def _ledger_entry(
    *,
    tenant_id: UUID,
    wallet_id: UUID,
    reservation_id: UUID,
    entry_type: str,
    amount_minor: int,
    currency: str,
    suffix: str,
) -> LedgerEntries:
    return LedgerEntries(
        id=uuid4(),
        tenant_id=tenant_id,
        wallet_account_id=wallet_id,
        reservation_id=reservation_id,
        entry_type=entry_type,
        amount_minor=amount_minor,
        currency=currency,
        reference_type="balance_reservation",
        reference_id=reservation_id,
        idempotency_key=f"reservation:{reservation_id}:{suffix}",
    )


def _billing_usage_from_record(record: UsageRecords) -> BillingUsage:
    return BillingUsage(
        input_tokens=int(record.input_tokens),
        output_tokens=int(record.output_tokens),
        image_count=int(record.image_count),
        video_seconds=int(record.video_seconds),
        audio_seconds=int(record.audio_seconds),
        character_count=int(record.character_count),
        audio_duration_ms=int(record.audio_duration_ms),
        video_duration_ms=int(record.video_duration_ms),
        storage_bytes=int(record.storage_bytes),
        billable_units=int(record.billable_units),
    )


def _apply_usage_charge(
    record: UsageRecords,
    *,
    price: PriceSnapshot,
    charge: Money,
) -> None:
    label = pricing_version(price)
    if int(record.charge_amount_minor) not in {0, charge.amount_minor}:
        raise BillingInvariantError
    record.pricing_version = label
    record.currency = charge.currency
    record.charge_amount_minor = charge.amount_minor


def _reservation_result(reservation: BalanceReservations) -> ReservationResult:
    status = reservation.status
    if status not in _RESERVATION_STATUSES:
        raise BillingInvariantError
    return ReservationResult(
        reservation_id=reservation.id,
        tenant_id=reservation.tenant_id,
        source_type=reservation.source_type,
        source_id=reservation.source_id,
        amount=Money(int(reservation.amount_minor), reservation.currency),
        status=cast(ReservationStatus, status),
        expires_at=_as_utc(reservation.expires_at),
    )


def _capture_result(
    *,
    reservation: BalanceReservations,
    charged_minor: int,
    released_minor: int,
    idempotent: bool,
) -> CaptureResult:
    result = _reservation_result(reservation)
    return CaptureResult(
        reservation=result,
        charged=Money(charged_minor, reservation.currency),
        released=Money(released_minor, reservation.currency),
        idempotent=idempotent,
    )


def _release_result(
    *,
    reservation: BalanceReservations,
    currency: str,
    released_minor: int,
    idempotent: bool,
) -> ReleaseResult:
    return ReleaseResult(
        reservation=_reservation_result(reservation),
        released=Money(released_minor, currency),
        idempotent=idempotent,
    )


def _resolve_existing_reservation(
    *,
    reservation: BalanceReservations,
    requested_amount: Money,
    requested_expires_at: datetime,
) -> ReservationResult:
    if reservation.currency != requested_amount.currency:
        raise BillingConflict(
            code=RESERVATION_IDEMPOTENCY_CONFLICT,
            message="相同业务请求的金额参数不一致",
        )
    if int(reservation.amount_minor) != requested_amount.amount_minor:
        raise BillingConflict(
            code=RESERVATION_IDEMPOTENCY_CONFLICT,
            message="相同业务请求的金额参数不一致",
        )
    if _as_utc(reservation.expires_at) != requested_expires_at:
        raise BillingConflict(
            code=RESERVATION_IDEMPOTENCY_CONFLICT,
            message="相同业务请求的过期参数不一致",
        )
    return _reservation_result(reservation)


def _capture_transition_error(
    status: str,
    actual: Money,
    reservation: BalanceReservations,
) -> BillingError:
    if status == "committed":
        return BillingConflict(code=CAPTURE_CONFLICT, message="该预留已按其他金额结算")
    if status in {"released", "expired"}:
        return BillingConflict(code=CAPTURE_CONFLICT, message="该预留当前不可结算")
    if status == "pending" and actual.amount_minor > int(reservation.amount_minor):
        return BillingConflict(code=CAPTURE_AMOUNT_EXCEEDED, message="结算金额超过预留上限")
    return BillingInvariantError()


def _assert_wallet_reservation_match(
    wallet: WalletAccounts,
    reservation: BalanceReservations,
) -> None:
    if (
        wallet.id != reservation.wallet_account_id
        or wallet.tenant_id != reservation.tenant_id
        or wallet.currency != reservation.currency
    ):
        raise BillingInvariantError


def _assert_currency(actual: Money, wallet_currency: str) -> None:
    if actual.currency != wallet_currency:
        raise BillingConflict(code=CURRENCY_MISMATCH, message="结算货币不一致")


def _require_money(value: Money) -> Money:
    if not isinstance(value, Money):
        raise BillingInputError(code="BILLING_INVALID_MONEY", message="金额参数无效")
    return value


def _require_positive_reservation_amount(value: Money) -> None:
    if value.amount_minor <= 0:
        raise BillingInputError(
            code="BILLING_INVALID_RESERVATION_AMOUNT",
            message="预留金额必须大于零",
        )


def _require_uuid(value: UUID, name: str) -> None:
    if not isinstance(value, UUID):
        raise BillingInputError(code="BILLING_INVALID_IDENTIFIER", message=f"{name}参数无效")


def _normalize_source_type(value: str) -> str:
    if not isinstance(value, str):
        raise BillingInputError(code="BILLING_INVALID_SOURCE", message="业务来源参数无效")
    normalized = value.strip().lower()
    if not _SOURCE_TYPE.fullmatch(normalized):
        raise BillingInputError(code="BILLING_INVALID_SOURCE", message="业务来源参数无效")
    return normalized


def _require_future_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise BillingInputError(code="BILLING_INVALID_EXPIRY", message="过期时间参数无效")
    normalized = value.astimezone(UTC)
    if normalized <= datetime.now(UTC):
        raise BillingInputError(code="BILLING_INVALID_EXPIRY", message="过期时间参数无效")
    return normalized


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_unique_violation(error: IntegrityError) -> bool:
    original = error.orig
    direct = getattr(original, "sqlstate", None)
    if direct == "23505":
        return True
    cause = getattr(original, "__cause__", None)
    return getattr(cause, "sqlstate", None) == "23505"


def _record_billing_error(error: BillingError) -> None:
    if isinstance(error, BillingInvariantError):
        record_billing_invariant()


__all__ = ["SqlAlchemyBillingService"]
