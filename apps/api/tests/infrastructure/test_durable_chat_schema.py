from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, Constraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable, DefaultClause

from app.infrastructure.models import Base


def _constraint[T: Constraint](
    table_name: str,
    constraint_type: type[T],
    name: str,
) -> T:
    table = Base.metadata.tables[table_name]
    found = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and constraint.name == name
    )
    return found


def _foreign_key(table_name: str, name: str) -> ForeignKeyConstraint:
    return _constraint(table_name, ForeignKeyConstraint, name)


def test_conversation_and_message_attempt_links_are_tenant_and_conversation_scoped() -> None:
    conversations = Base.metadata.tables["conversations"]
    assert conversations.c.active_inference_request_id.nullable is True
    assert conversations.c.version.type.python_type is int
    assert conversations.c.version.server_default is not None
    version_default = cast(DefaultClause, conversations.c.version.server_default)
    assert str(version_default.arg) == "0"
    assert _constraint(
        "conversations",
        CheckConstraint,
        "ck_conversations_version_nonnegative",
    ).sqltext.text == "version >= 0"
    active_fk = _foreign_key(
        "conversations",
        "fk_conversations_active_inference_request_tenant",
    )
    assert active_fk.column_keys == ["tenant_id", "active_inference_request_id", "id"]
    assert [element.target_fullname for element in active_fk.elements] == [
        "inference_requests.tenant_id",
        "inference_requests.id",
        "inference_requests.conversation_id",
    ]
    assert active_fk.use_alter is True

    messages = Base.metadata.tables["messages"]
    assert messages.c.request_id.nullable is True
    assert messages.c.legacy_content.nullable is True
    content_check = _constraint(
        "messages",
        CheckConstraint,
        "ck_messages_content_text_object",
    )
    assert "role NOT IN ('user', 'assistant')" in content_check.sqltext.text
    assert "jsonb_typeof(content->'text') = 'string'" in content_check.sqltext.text
    message_fk = _foreign_key("messages", "fk_messages_inference_request_tenant")
    assert message_fk.column_keys == ["tenant_id", "request_id", "conversation_id", "id"]
    assert [element.target_fullname for element in message_fk.elements] == [
        "inference_requests.tenant_id",
        "inference_requests.id",
        "inference_requests.conversation_id",
        "inference_requests.message_id",
    ]
    assert message_fk.use_alter is True
    _constraint("messages", UniqueConstraint, "uq_messages_tenant_id_conversation")


def test_inference_request_durable_state_and_active_partial_unique_index() -> None:
    requests = Base.metadata.tables["inference_requests"]
    expected_columns = {
        "request_hash",
        "last_event_sequence",
        "cancel_requested_at",
        "worker_id",
        "lease_token",
        "lease_expires_at",
        "last_heartbeat_at",
        "provider_started_at",
        "terminal_reason",
        "sanitized_error_details",
        "parent_request_id",
    }
    assert expected_columns <= set(requests.c.keys())
    assert requests.c.request_hash.nullable is False
    assert requests.c.last_event_sequence.nullable is False
    event_default = cast(DefaultClause, requests.c.last_event_sequence.server_default)
    assert str(event_default.arg) == "-1"
    status_check = _constraint(requests.name, CheckConstraint, "ck_inference_requests_status_values")
    assert "stop_requested" in status_check.sqltext.text
    _constraint(
        requests.name,
        UniqueConstraint,
        "uq_inference_requests_tenant_id_conversation",
    )
    _constraint(
        requests.name,
        UniqueConstraint,
        "uq_inference_requests_tenant_id_conversation_message",
    )
    assert _foreign_key(
        requests.name,
        "fk_inference_requests_message_tenant",
    ).column_keys == ["tenant_id", "message_id", "conversation_id"]

    active_index = next(
        index for index in requests.indexes if index.name == "uq_inference_requests_active_conversation"
    )
    assert active_index.unique is True
    assert [column.name for column in active_index.columns] == ["tenant_id", "conversation_id"]
    assert "stop_requested" in str(active_index.dialect_options["postgresql"]["where"])


def test_chat_stream_events_have_monotonic_keys_and_one_terminal_event() -> None:
    events = Base.metadata.tables["chat_stream_events"]
    assert {
        "tenant_id",
        "inference_request_id",
        "sequence_no",
        "event_type",
        "payload",
        "created_at",
    } <= set(events.c.keys())
    _constraint(events.name, CheckConstraint, "ck_chat_stream_events_sequence_nonnegative")
    event_type = _constraint(events.name, CheckConstraint, "ck_chat_stream_events_event_type_values")
    assert all(value in event_type.sqltext.text for value in ("started", "delta", "completed", "stopped", "failed"))
    request_fk = _foreign_key(events.name, "fk_chat_stream_events_inference_request_tenant")
    assert request_fk.column_keys == ["tenant_id", "inference_request_id"]
    unique = _constraint(events.name, UniqueConstraint, "uq_chat_stream_events_request_sequence")
    assert [column.name for column in unique.columns] == [
        "tenant_id",
        "inference_request_id",
        "sequence_no",
    ]

    terminal = next(index for index in events.indexes if index.name == "uq_chat_stream_events_terminal")
    assert terminal.unique is True
    assert "completed" in str(terminal.dialect_options["postgresql"]["where"])
    assert "failed" in str(terminal.dialect_options["postgresql"]["where"])

    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    ddl = str(CreateTable(events).compile(dialect=dialect))
    assert "JSONB" in ddl
    assert "sequence_no >= 0" in ddl
    for index in events.indexes:
        assert str(CreateIndex(index).compile(dialect=dialect))


def test_durable_chat_migration_generates_postgresql_upgrade_and_downgrade_sql(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))

    command.upgrade(config, "head", sql=True)
    upgrade_sql = capsys.readouterr().out
    assert "20260824_0005" in upgrade_sql
    assert "CREATE TABLE chat_stream_events" in upgrade_sql
    assert "CREATE UNIQUE INDEX uq_chat_stream_events_terminal" in upgrade_sql
    assert "jsonb_build_object" in upgrade_sql
    assert "SET legacy_content = content" in upgrade_sql
    assert "ir.conversation_id IS DISTINCT FROM message.conversation_id" in upgrade_sql
    assert "migration_cancelled_legacy_active_request" in upgrade_sql
    assert "FOREIGN KEY(tenant_id, active_inference_request_id, id)" in upgrade_sql

    command.downgrade(config, "20260824_0005:20260824_0004", sql=True)
    downgrade_sql = capsys.readouterr().out
    assert "DROP TABLE chat_stream_events" in downgrade_sql
    assert "DROP CONSTRAINT uq_inference_requests_tenant_id_conversation_message" in downgrade_sql
    assert "SET content = legacy_content" in downgrade_sql
    assert "DROP CONSTRAINT uq_inference_requests_tenant_id_conversation" in downgrade_sql
    assert "DROP COLUMN active_inference_request_id" in downgrade_sql
