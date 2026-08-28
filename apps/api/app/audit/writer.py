from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.models import AuditEvents

_ACTION = re.compile(r"^[a-z][a-z0-9._:-]{2,159}$")
_RESOURCE_TYPE = re.compile(r"^[a-z][a-z0-9._:-]{1,63}$")
_SENSITIVE_KEYS = frozenset(
    {"authorization", "cookie", "password", "secret", "session_token", "token"}
)


@dataclass(frozen=True, slots=True)
class AuditContext:
    request_id: UUID | None = None
    ip_address: str | None = None
    user_agent: str | None = None


def append_audit_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: UUID | None,
    context: AuditContext,
    payload: Mapping[str, Any] | None = None,
) -> None:
    if _ACTION.fullmatch(action) is None:
        raise ValueError("audit action is invalid")
    if _RESOURCE_TYPE.fullmatch(resource_type) is None:
        raise ValueError("audit resource type is invalid")
    safe_payload = dict(payload or {})
    if any(str(key).casefold() in _SENSITIVE_KEYS for key in safe_payload):
        raise ValueError("audit payload contains a sensitive key")
    session.add(
        AuditEvents(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=context.request_id,
            payload=safe_payload,
            ip_address=context.ip_address,
            user_agent=context.user_agent[:512] if context.user_agent else None,
        )
    )


__all__ = ["AuditContext", "append_audit_event"]
