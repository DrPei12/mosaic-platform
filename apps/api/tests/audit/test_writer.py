from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.audit.writer import AuditContext, append_audit_event


class _Session:
    def __init__(self) -> None:
        self.rows: list[Any] = []

    def add(self, row: Any) -> None:
        self.rows.append(row)


def test_audit_writer_records_only_structured_metadata() -> None:
    session = _Session()
    request_id = uuid4()

    append_audit_event(
        session,  # type: ignore[arg-type]
        tenant_id=uuid4(),
        actor_user_id=uuid4(),
        action="auth.session.revoke",
        resource_type="auth_session",
        resource_id=uuid4(),
        context=AuditContext(
            request_id=request_id,
            ip_address="127.0.0.1",
            user_agent="a" * 600,
        ),
        payload={"scope": "self"},
    )

    row = session.rows[0]
    assert row.request_id == request_id
    assert row.payload == {"scope": "self"}
    assert len(row.user_agent) == 512


@pytest.mark.parametrize("key", ["password", "TOKEN", "cookie", "authorization"])
def test_audit_writer_rejects_sensitive_payload_keys(key: str) -> None:
    with pytest.raises(ValueError, match="sensitive"):
        append_audit_event(
            SimpleNamespace(add=lambda _row: None),  # type: ignore[arg-type]
            tenant_id=uuid4(),
            actor_user_id=uuid4(),
            action="auth.session.create",
            resource_type="auth_session",
            resource_id=uuid4(),
            context=AuditContext(),
            payload={key: "must-not-be-stored"},
        )
