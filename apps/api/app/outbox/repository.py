"""Database boundary for a fenced transactional outbox.

The relay never holds an ``AsyncSession`` transaction while publishing.  This
repository commits a claim before returning rows and uses the claim owner plus
an opaque lease token in every mark predicate.

The current checkout's ``OutboxEvents`` model predates fencing.  The SQL
implementation therefore checks for the required columns and fails closed
until the corresponding model/migration change is supplied by the schema
owner.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from sqlalchemy import Table, case, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.models import OutboxEvents
from app.outbox.types import (
    ClaimedOutboxEvent,
    OutboxErrorDetails,
    OutboxEvent,
    sanitize_error_details,
)

_MAX_LIMIT = 500
_MAX_LEASE_SECONDS = 86_400
_MAX_ATTEMPTS = 1_000
_REQUIRED_FENCING_COLUMNS = ("claim_owner", "lease_token", "lease_expires_at")


class OutboxSchemaError(RuntimeError):
    """Raised when the database model cannot provide fencing guarantees."""


class OutboxRepository(Protocol):
    async def claim(
        self,
        *,
        owner: str,
        event_types: str | Collection[str] | None = None,
        event_type: str | None = None,
        limit: int = 50,
        tenant_id: uuid.UUID | None = None,
        lease_seconds: int = 60,
        max_attempts: int = 5,
    ) -> Sequence[ClaimedOutboxEvent]: ...

    async def mark_published(
        self,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        aggregate_version: int,
        owner: str,
        lease_token: uuid.UUID,
    ) -> bool: ...

    async def mark_retry(
        self,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        aggregate_version: int,
        owner: str,
        lease_token: uuid.UUID,
        details: OutboxErrorDetails | Mapping[str, object],
        retry_at: datetime,
        max_attempts: int = 5,
    ) -> bool: ...


def _validate_owner(owner: str) -> str:
    normalized = owner.strip()
    if not normalized or len(normalized) > 200:
        raise ValueError("outbox claim owner must be 1 to 200 characters")
    return normalized


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= _MAX_LIMIT:
        raise ValueError(f"outbox claim limit must be between 1 and {_MAX_LIMIT}")


def _validate_lease_seconds(lease_seconds: int) -> None:
    if not 1 <= lease_seconds <= _MAX_LEASE_SECONDS:
        raise ValueError(
            f"outbox lease must be between 1 and {_MAX_LEASE_SECONDS} seconds"
        )


def _validate_max_attempts(max_attempts: int) -> None:
    if not 1 <= max_attempts <= _MAX_ATTEMPTS:
        raise ValueError(f"outbox max_attempts must be between 1 and {_MAX_ATTEMPTS}")


def normalize_event_types(
    event_types: str | Collection[str] | None,
    *,
    event_type: str | None = None,
) -> tuple[str, ...] | None:
    """Normalize singular/plural filter forms without widening the query."""

    if event_types is not None and event_type is not None:
        raise ValueError("pass event_type or event_types, not both")
    selected: str | Collection[str] | None = event_type if event_type is not None else event_types
    if selected is None:
        return None
    values = (selected,) if isinstance(selected, str) else tuple(selected)
    if any(not isinstance(value, str) for value in values):
        raise ValueError("outbox event_type filter must contain strings")
    normalized = tuple(dict.fromkeys(value.strip() for value in values))
    if any(not value for value in normalized):
        raise ValueError("outbox event_type filter must not contain blank values")
    # The same grammar is enforced by EventEnvelope.  Keep the repository
    # boundary strict so an invalid route cannot be claimed accidentally.
    from app.outbox.types import _EVENT_TYPE

    if any(_EVENT_TYPE.fullmatch(value) is None for value in normalized):
        raise ValueError("outbox event_type filter contains an invalid value")
    return normalized


class SqlAlchemyOutboxRepository:
    """PostgreSQL repository with row-lock claims and fenced mark updates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def required_fencing_columns() -> tuple[str, ...]:
        return _REQUIRED_FENCING_COLUMNS

    def _fencing_columns(self) -> dict[str, Any]:
        columns = OutboxEvents.__table__.c
        missing = tuple(name for name in _REQUIRED_FENCING_COLUMNS if name not in columns)
        if missing:
            missing_text = ", ".join(missing)
            raise OutboxSchemaError(
                "outbox_events is missing fencing columns: "
                f"{missing_text}; add them before enabling the relay"
            )
        return {name: columns[name] for name in _REQUIRED_FENCING_COLUMNS}

    async def claim(
        self,
        *,
        owner: str,
        event_types: str | Collection[str] | None = None,
        event_type: str | None = None,
        limit: int = 50,
        tenant_id: uuid.UUID | None = None,
        lease_seconds: int = 60,
        max_attempts: int = 5,
    ) -> Sequence[ClaimedOutboxEvent]:
        owner = _validate_owner(owner)
        _validate_limit(limit)
        _validate_lease_seconds(lease_seconds)
        _validate_max_attempts(max_attempts)
        selected_types = normalize_event_types(event_types, event_type=event_type)
        if selected_types == ():
            return ()
        fencing = self._fencing_columns()
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=lease_seconds)
        table = cast(Table, OutboxEvents.__table__)
        async with self._session.begin():
            lease_available = or_(
                fencing["lease_expires_at"].is_(None),
                fencing["lease_expires_at"] <= now,
            )
            predicates: list[Any] = [
                table.c.status == "pending",
                table.c.available_at <= now,
                table.c.attempts < max_attempts,
                lease_available,
            ]
            if tenant_id is not None:
                predicates.append(table.c.tenant_id == tenant_id)
            if selected_types is not None:
                predicates.append(table.c.event_type.in_(selected_types))
            # A process can crash after taking its final lease.  Once that
            # lease expires, do not leave the row pending forever: move it to
            # the terminal failed state with a stable, non-sensitive reason.
            exhausted_predicates: list[Any] = [
                table.c.status == "pending",
                table.c.available_at <= now,
                table.c.attempts >= max_attempts,
                lease_available,
            ]
            if tenant_id is not None:
                exhausted_predicates.append(table.c.tenant_id == tenant_id)
            if selected_types is not None:
                exhausted_predicates.append(table.c.event_type.in_(selected_types))
            await self._session.execute(
                update(table)
                .where(*exhausted_predicates)
                .values(
                    {
                        "status": "failed",
                        "sanitized_error_details": {
                            "code": "OUTBOX_MAX_ATTEMPTS",
                            "phase": "claim",
                            "retryable": False,
                        },
                        fencing["claim_owner"]: None,
                        fencing["lease_token"]: None,
                        fencing["lease_expires_at"]: None,
                    }
                )
            )
            query = (
                select(OutboxEvents)
                .where(*predicates)
                .order_by(table.c.created_at, table.c.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            rows = tuple((await self._session.execute(query)).scalars())
            claimed: list[ClaimedOutboxEvent] = []
            for row in rows:
                token = uuid.uuid4()
                attempts = row.attempts + 1
                await self._session.execute(
                    update(table)
                    .where(
                        table.c.tenant_id == row.tenant_id,
                        table.c.id == row.id,
                        table.c.status == "pending",
                    )
                    .values(
                        attempts=attempts,
                        available_at=lease_until,
                        claim_owner=owner,
                        lease_token=token,
                        lease_expires_at=lease_until,
                    )
                )
                claimed.append(
                    _event_from_row(
                        row,
                        attempts=attempts,
                        claim_owner=owner,
                        lease_token=token,
                        lease_expires_at=lease_until,
                    )
                )
            return tuple(claimed)

    async def mark_published(
        self,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        aggregate_version: int,
        owner: str,
        lease_token: uuid.UUID,
    ) -> bool:
        owner = _validate_owner(owner)
        fencing = self._fencing_columns()
        table = cast(Table, OutboxEvents.__table__)
        now = datetime.now(UTC)
        async with self._session.begin():
            result = await self._session.execute(
                update(table)
                .where(
                    table.c.tenant_id == tenant_id,
                    table.c.id == event_id,
                    table.c.aggregate_version == aggregate_version,
                    table.c.status == "pending",
                    fencing["claim_owner"] == owner,
                    fencing["lease_token"] == lease_token,
                )
                .values(
                    {
                        "status": "published",
                        "published_at": now,
                        "sanitized_error_details": None,
                        fencing["claim_owner"]: None,
                        fencing["lease_token"]: None,
                        fencing["lease_expires_at"]: None,
                    }
                )
            )
            return cast(CursorResult[Any], result).rowcount == 1

    async def mark_retry(
        self,
        *,
        tenant_id: uuid.UUID,
        event_id: uuid.UUID,
        aggregate_version: int,
        owner: str,
        lease_token: uuid.UUID,
        details: OutboxErrorDetails | Mapping[str, object],
        retry_at: datetime,
        max_attempts: int = 5,
    ) -> bool:
        owner = _validate_owner(owner)
        _validate_max_attempts(max_attempts)
        fencing = self._fencing_columns()
        if isinstance(details, OutboxErrorDetails):
            safe_details = details
        else:
            safe_details = sanitize_error_details(dict(details))
        retry_at = retry_at.astimezone(UTC) if retry_at.tzinfo else retry_at.replace(tzinfo=UTC)
        table = cast(Table, OutboxEvents.__table__)
        retryable = safe_details.retryable
        can_retry = table.c.attempts < max_attempts
        status = case((can_retry & retryable, "pending"), else_="failed")
        available_at = case((can_retry & retryable, retry_at), else_=datetime.now(UTC))
        async with self._session.begin():
            result = await self._session.execute(
                update(table)
                .where(
                    table.c.tenant_id == tenant_id,
                    table.c.id == event_id,
                    table.c.aggregate_version == aggregate_version,
                    table.c.status == "pending",
                    fencing["claim_owner"] == owner,
                    fencing["lease_token"] == lease_token,
                )
                .values(
                    {
                        "status": status,
                        "available_at": available_at,
                        "sanitized_error_details": safe_details.as_mapping(),
                        fencing["claim_owner"]: None,
                        fencing["lease_token"]: None,
                        fencing["lease_expires_at"]: None,
                    }
                )
            )
            return cast(CursorResult[Any], result).rowcount == 1

    # Explicit aliases make this boundary easy to adapt to the existing
    # generation repository vocabulary without coupling the relay to it.
    async def mark_outbox_published(self, **kwargs: Any) -> bool:
        return await self.mark_published(**kwargs)

    async def claim_outbox(self, **kwargs: Any) -> Sequence[ClaimedOutboxEvent]:
        return await self.claim(**kwargs)

    async def mark_outbox_retry(self, **kwargs: Any) -> bool:
        return await self.mark_retry(**kwargs)

    async def mark_outbox_failed(self, **kwargs: Any) -> bool:
        """Compatibility name; ``mark_retry`` decides pending vs terminal failed."""

        return await self.mark_retry(**kwargs)


def _event_from_row(
    row: OutboxEvents,
    *,
    attempts: int,
    claim_owner: str,
    lease_token: uuid.UUID,
    lease_expires_at: datetime,
) -> ClaimedOutboxEvent:
    return OutboxEvent(
        event_id=row.id,
        tenant_id=row.tenant_id,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        aggregate_version=row.aggregate_version,
        payload=dict(row.payload or {}),
        attempts=attempts,
        available_at=lease_expires_at,
        claim_owner=claim_owner,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
    )


__all__ = [
    "OutboxRepository",
    "OutboxSchemaError",
    "SqlAlchemyOutboxRepository",
    "normalize_event_types",
]
