"""Add durable conversation state and replayable chat stream events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0005"
down_revision: str | None = "20260824_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Conversation CAS state and the active request pointer are added before
    # the corresponding request/message links.  The referenced tables already
    # exist since 0002; creating these constraints explicitly keeps the
    # migration valid even though the metadata contains a request/message
    # cycle.
    op.add_column(
        "conversations",
        sa.Column("active_inference_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint(
        "ck_conversations_version_nonnegative",
        "conversations",
        "version >= 0",
    )

    op.add_column(
        "messages",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("legacy_content", postgresql.JSONB(), nullable=True),
    )
    # The old foundation did not guarantee that a message UUID carried its
    # conversation.  Install the target key before replacing the request FK.
    op.create_unique_constraint(
        "uq_messages_tenant_id_conversation",
        "messages",
        ["tenant_id", "id", "conversation_id"],
    )
    # Only public user/assistant text rows require the text envelope. Preserve
    # any legacy JSON losslessly in a dedicated nullable column so a downgrade can
    # restore it; system/tool payloads remain untouched.
    op.execute(
        sa.text(
            "UPDATE messages "
            "SET legacy_content = content, "
            "content = jsonb_build_object('type', 'text', 'text', "
            "COALESCE(CASE WHEN jsonb_typeof(content) = 'object' "
            "AND jsonb_typeof(content->'text') = 'string' THEN content->>'text' END, "
            "CASE WHEN jsonb_typeof(content) = 'string' THEN content #>> '{}' "
            "ELSE content::text END)) "
            "WHERE role IN ('user', 'assistant') AND NOT ("
            "jsonb_typeof(content) = 'object' AND content ? 'type' "
            "AND content->>'type' = 'text' AND content ? 'text' "
            "AND jsonb_typeof(content->'text') = 'string')"
        )
    )
    op.create_check_constraint(
        "ck_messages_content_text_object",
        "messages",
        "role NOT IN ('user', 'assistant') OR ("
        "jsonb_typeof(content) = 'object' AND content ? 'type' "
        "AND content->>'type' = 'text' AND content ? 'text' "
        "AND jsonb_typeof(content->'text') = 'string')",
    )
    op.create_index("ix_messages_tenant_request", "messages", ["tenant_id", "request_id"])
    op.drop_constraint("fk_inference_requests_message_tenant", "inference_requests", type_="foreignkey")

    # request_hash was nullable in the foundation schema.  Null/empty legacy
    # rows receive a stable, non-secret marker derived from their immutable
    # internal UUID before the NOT NULL invariant is installed.
    op.add_column(
        "inference_requests",
        sa.Column(
            "last_event_sequence",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("-1"),
        ),
    )
    op.add_column(
        "inference_requests",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("inference_requests", sa.Column("worker_id", sa.String(128), nullable=True))
    op.add_column(
        "inference_requests",
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "inference_requests",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "inference_requests",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "inference_requests",
        sa.Column("provider_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "inference_requests",
        sa.Column("terminal_reason", sa.String(160), nullable=True),
    )
    op.add_column(
        "inference_requests",
        sa.Column("sanitized_error_details", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "inference_requests",
        sa.Column("parent_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE inference_requests "
            "SET request_hash = 'legacy:' || id::text "
            "WHERE request_hash IS NULL OR request_hash = ''"
        )
    )
    # The old two-column request->message FK allowed a request's conversation
    # to be null or to disagree with its referenced message. The message is the
    # authoritative legacy link; repair that column before installing the
    # conversation-scoped FK.
    op.execute(
        sa.text(
            "UPDATE inference_requests AS ir "
            "SET conversation_id = message.conversation_id "
            "FROM messages AS message "
            "WHERE ir.tenant_id = message.tenant_id "
            "AND ir.message_id = message.id "
            "AND ir.conversation_id IS DISTINCT FROM message.conversation_id"
        )
    )
    op.alter_column("inference_requests", "request_hash", nullable=False)
    op.drop_constraint("ck_inference_requests_status_values", "inference_requests", type_="check")
    op.create_check_constraint(
        "ck_inference_requests_status_values",
        "inference_requests",
        "status IN ('queued', 'running', 'submitted_unknown', 'stopped', "
        "'stop_requested', 'succeeded', 'failed', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_inference_requests_request_hash_nonempty",
        "inference_requests",
        "request_hash <> ''",
    )
    op.create_check_constraint(
        "ck_inference_requests_last_event_sequence_floor",
        "inference_requests",
        "last_event_sequence >= -1",
    )
    op.create_check_constraint(
        "ck_inference_requests_message_requires_conversation",
        "inference_requests",
        "message_id IS NULL OR conversation_id IS NOT NULL",
    )
    op.create_unique_constraint(
        "uq_inference_requests_tenant_id_conversation",
        "inference_requests",
        ["tenant_id", "id", "conversation_id"],
    )
    op.create_unique_constraint(
        "uq_inference_requests_tenant_id_conversation_message",
        "inference_requests",
        ["tenant_id", "id", "conversation_id", "message_id"],
    )
    op.create_foreign_key(
        "fk_inference_requests_message_tenant",
        "inference_requests",
        "messages",
        ["tenant_id", "message_id", "conversation_id"],
        ["tenant_id", "id", "conversation_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_inference_requests_parent_request_tenant",
        "inference_requests",
        "inference_requests",
        ["tenant_id", "parent_request_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    # 0004 had no single-active-request invariant or durable stream log. It is
    # unsafe to resume an unknown legacy queued/running Provider attempt after
    # the upgrade, so fail closed by terminalizing all such conversation-bound
    # requests before installing the unique active index.
    op.execute(
        sa.text(
            "UPDATE messages AS message SET status = 'stopped', "
            "updated_at = CURRENT_TIMESTAMP "
            "FROM inference_requests AS ir "
            "WHERE ir.tenant_id = message.tenant_id "
            "AND ir.message_id = message.id "
            "AND ir.conversation_id = message.conversation_id "
            "AND ir.conversation_id IS NOT NULL "
            "AND ir.status IN ('queued', 'running', 'submitted_unknown') "
            "AND message.status = 'streaming'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE inference_requests SET status = 'cancelled', "
            "completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP), "
            "terminal_reason = 'migration_cancelled_legacy_active_request', "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE conversation_id IS NOT NULL "
            "AND status IN ('queued', 'running', 'submitted_unknown')"
        )
    )
    op.create_index(
        "uq_inference_requests_active_conversation",
        "inference_requests",
        ["tenant_id", "conversation_id"],
        unique=True,
        postgresql_where=sa.text(
            "conversation_id IS NOT NULL AND status IN "
            "('queued', 'running', 'submitted_unknown', 'stop_requested')"
        ),
    )
    op.create_foreign_key(
        "fk_conversations_active_inference_request_tenant",
        "conversations",
        "inference_requests",
        ["tenant_id", "active_inference_request_id", "id"],
        ["tenant_id", "id", "conversation_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_messages_inference_request_tenant",
        "messages",
        "inference_requests",
        ["tenant_id", "request_id", "conversation_id", "id"],
        ["tenant_id", "id", "conversation_id", "message_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "chat_stream_events",
        sa.Column("inference_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_no", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "sequence_no >= 0",
            name="ck_chat_stream_events_sequence_nonnegative",
        ),
        sa.CheckConstraint(
            "event_type IN ('started', 'delta', 'completed', 'stopped', 'failed')",
            name="ck_chat_stream_events_event_type_values",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_chat_stream_events_tenant_id_tenants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "inference_request_id"],
            ["inference_requests.tenant_id", "inference_requests.id"],
            name="fk_chat_stream_events_inference_request_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_chat_stream_events_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "inference_request_id",
            "sequence_no",
            name="uq_chat_stream_events_request_sequence",
        ),
    )
    op.create_index(
        "ix_chat_stream_events_tenant_request_sequence",
        "chat_stream_events",
        ["tenant_id", "inference_request_id", "sequence_no"],
    )
    op.create_index(
        "uq_chat_stream_events_terminal",
        "chat_stream_events",
        ["tenant_id", "inference_request_id"],
        unique=True,
        postgresql_where=sa.text("event_type IN ('completed', 'stopped', 'failed')"),
    )


def downgrade() -> None:
    op.drop_index("uq_chat_stream_events_terminal", table_name="chat_stream_events")
    op.drop_index(
        "ix_chat_stream_events_tenant_request_sequence",
        table_name="chat_stream_events",
    )
    op.drop_table("chat_stream_events")

    op.drop_index("uq_inference_requests_active_conversation", table_name="inference_requests")
    op.drop_constraint(
        "fk_inference_requests_parent_request_tenant",
        "inference_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_messages_inference_request_tenant",
        "messages",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_conversations_active_inference_request_tenant",
        "conversations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_inference_requests_message_tenant",
        "inference_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_inference_requests_tenant_id_conversation_message",
        "inference_requests",
        type_="unique",
    )
    op.drop_constraint(
        "uq_inference_requests_tenant_id_conversation",
        "inference_requests",
        type_="unique",
    )
    op.drop_constraint(
        "uq_messages_tenant_id_conversation",
        "messages",
        type_="unique",
    )
    op.create_foreign_key(
        "fk_inference_requests_message_tenant",
        "inference_requests",
        "messages",
        ["tenant_id", "message_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_inference_requests_last_event_sequence_floor",
        "inference_requests",
        type_="check",
    )
    op.drop_constraint(
        "ck_inference_requests_message_requires_conversation",
        "inference_requests",
        type_="check",
    )
    # A stop intent has no representation in the 0004 status enum.  Preserve
    # its terminal meaning while making the downgrade executable on populated
    # databases instead of recreating an old check that immediately fails.
    op.execute(
        sa.text(
            "UPDATE inference_requests SET status = 'stopped' "
            "WHERE status = 'stop_requested'"
        )
    )
    op.drop_constraint(
        "ck_inference_requests_request_hash_nonempty",
        "inference_requests",
        type_="check",
    )
    op.drop_constraint("ck_inference_requests_status_values", "inference_requests", type_="check")
    op.create_check_constraint(
        "ck_inference_requests_status_values",
        "inference_requests",
        "status IN ('queued', 'running', 'submitted_unknown', 'stopped', "
        "'succeeded', 'failed', 'cancelled')",
    )
    op.alter_column("inference_requests", "request_hash", nullable=True)
    for column in (
        "parent_request_id",
        "sanitized_error_details",
        "terminal_reason",
        "provider_started_at",
        "last_heartbeat_at",
        "lease_expires_at",
        "lease_token",
        "worker_id",
        "cancel_requested_at",
        "last_event_sequence",
    ):
        op.drop_column("inference_requests", column)

    op.drop_index("ix_messages_tenant_request", table_name="messages")
    op.drop_constraint("ck_messages_content_text_object", "messages", type_="check")
    op.execute(
        sa.text(
            "UPDATE messages SET content = legacy_content "
            "WHERE legacy_content IS NOT NULL"
        )
    )
    op.drop_column("messages", "legacy_content")
    op.drop_column("messages", "request_id")

    op.drop_constraint("ck_conversations_version_nonnegative", "conversations", type_="check")
    op.drop_column("conversations", "version")
    op.drop_column("conversations", "active_inference_request_id")
