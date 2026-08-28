"""Create the production multi-tenant business schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("tenants",
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("slug = lower(slug)", name="ck_tenants_slug_lowercase"),
        sa.CheckConstraint("status IN ('active', 'suspended', 'closed')", name="ck_tenants_status_values"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_status", "tenants", ["status"])

    op.create_table("users",
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(160)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        sa.CheckConstraint("failed_login_count >= 0", name="ck_users_failed_login_count_nonnegative"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status_values"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table("memberships",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'billing_viewer')", name="ck_memberships_role_values"),
        sa.CheckConstraint("status IN ('invited', 'active', 'suspended', 'removed')", name="ck_memberships_status_values"),
        sa.ForeignKeyConstraint(["tenant_id", "invited_by_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_memberships_invited_by_membership", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_memberships_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_memberships_user_id_users", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
    )
    op.create_index("ix_memberships_tenant_status", "memberships", ["tenant_id", "status"])

    op.create_table("auth_sessions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("csrf_token_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("ip_address", postgresql.INET()),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("status IN ('active', 'revoked', 'expired')", name="ck_auth_sessions_status_values"),
        sa.ForeignKeyConstraint(["tenant_id", "user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_auth_sessions_membership", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_auth_sessions_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("csrf_token_hash", name="uq_auth_sessions_csrf_token_hash"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_auth_sessions_tenant_id_id"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_expiry", "auth_sessions", ["tenant_id", "expires_at"])
    op.create_index("ix_auth_sessions_user_expiry", "auth_sessions", ["tenant_id", "user_id", "expires_at"])

    op.create_table("product_models",
        sa.Column("model_key", sa.String(160), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("modality", sa.String(32), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("pricing_summary", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("modality IN ('text', 'image', 'video', 'audio', 'embedding', 'rerank', 'multimodal')", name="ck_product_models_modality_values"),
        sa.CheckConstraint("status IN ('active', 'hidden', 'deprecated')", name="ck_product_models_status_values"),
        sa.CheckConstraint("task_type IN ('chat', 'text_to_image', 'text_to_video', 'image_to_video', 'tts')", name="ck_product_models_task_type_values"),
        sa.UniqueConstraint("model_key", name="uq_product_models_model_key"),
    )
    op.create_index("ix_product_models_modality", "product_models", ["modality", "status"])

    op.create_table("provider_endpoints",
        sa.Column("endpoint_key", sa.String(120), nullable=False),
        sa.Column("provider_name", sa.String(120), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("secret_ref", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("protocol IN ('openai_compatible', 'dashscope_http', 'dashscope_async')", name="ck_provider_endpoints_protocol_values"),
        sa.CheckConstraint("status IN ('active', 'disabled', 'degraded')", name="ck_provider_endpoints_status_values"),
        sa.CheckConstraint("timeout_ms > 0", name="ck_provider_endpoints_timeout_positive"),
        sa.UniqueConstraint("endpoint_key", name="uq_provider_endpoints_endpoint_key"),
    )
    op.create_index("ix_provider_endpoints_status", "provider_endpoints", ["status"])

    op.create_table("model_deployments",
        sa.Column("product_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_endpoint_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_model_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False),
        sa.Column("routing_config", postgresql.JSONB(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("concurrency_limit > 0", name="ck_model_deployments_concurrency_positive"),
        sa.CheckConstraint("priority >= 0", name="ck_model_deployments_priority_nonnegative"),
        sa.CheckConstraint("status IN ('active', 'disabled', 'draining')", name="ck_model_deployments_status_values"),
        sa.ForeignKeyConstraint(["product_model_id"], ["product_models.id"], name="fk_model_deployments_product_model", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_endpoint_id"], ["provider_endpoints.id"], name="fk_model_deployments_provider_endpoint", ondelete="RESTRICT"),
        sa.UniqueConstraint("product_model_id", "provider_endpoint_id", name="uq_model_deployments_model_endpoint"),
    )
    op.create_index("ix_model_deployments_model_status", "model_deployments", ["product_model_id", "status"])

    op.create_table("tenant_model_entitlements",
        sa.Column("product_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["product_model_id"], ["product_models.id"], name="fk_tenant_model_entitlements_product_model", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_tenant_model_entitlements_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tenant_model_entitlements_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "product_model_id", name="uq_tenant_model_entitlements_tenant_model"),
    )
    op.create_index("ix_tenant_model_entitlements_model_enabled", "tenant_model_entitlements", ["product_model_id", "enabled"])
    op.create_index("ix_tenant_model_entitlements_tenant_enabled", "tenant_model_entitlements", ["tenant_id", "enabled"])

    op.create_table("conversations",
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(240)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_conversations_status_values"),
        sa.ForeignKeyConstraint(["tenant_id", "created_by_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_conversations_created_by_membership", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "product_model_id"], ["tenant_model_entitlements.tenant_id", "tenant_model_entitlements.product_model_id"], name="fk_conversations_model_entitlement", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_model_id"], ["product_models.id"], name="fk_conversations_product_model", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_conversations_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id_id"),
    )
    op.create_index("ix_conversations_tenant_model", "conversations", ["tenant_id", "product_model_id"])
    op.create_index("ix_conversations_tenant_updated", "conversations", ["tenant_id", "updated_at"])

    op.create_table("messages",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("provider_model_id", sa.String(200)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("role IN ('system', 'user', 'assistant', 'tool')", name="ck_messages_role_values"),
        sa.CheckConstraint("status IN ('accepted', 'streaming', 'completed', 'failed', 'stopped')", name="ck_messages_status_values"),
        sa.ForeignKeyConstraint(["tenant_id", "author_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_messages_author_membership", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], name="fk_messages_conversation_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_messages_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "conversation_id", "sequence_no", name="uq_messages_conversation_sequence"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_messages_tenant_id_id"),
    )
    op.create_index("ix_messages_tenant_conversation_sequence", "messages", ["tenant_id", "conversation_id", "sequence_no"])

    op.create_table("inference_requests",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("message_id", postgresql.UUID(as_uuid=True)),
        sa.Column("model_deployment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("provider_task_id", sa.String(255)),
        sa.Column("request_hash", sa.String(128)),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("latency_ms", sa.BigInteger()),
        sa.Column("error_code", sa.String(120)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("status IN ('queued', 'running', 'submitted_unknown', 'stopped', 'succeeded', 'failed', 'cancelled')", name="ck_inference_requests_status_values"),
        sa.CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ck_inference_requests_tokens_nonnegative"),
        sa.ForeignKeyConstraint(["tenant_id", "actor_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_inference_requests_actor_membership", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], name="fk_inference_requests_conversation_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "message_id"], ["messages.tenant_id", "messages.id"], name="fk_inference_requests_message_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_deployment_id"], ["model_deployments.id"], name="fk_inference_requests_model_deployment", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_inference_requests_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("request_id", name="uq_inference_requests_request_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inference_requests_tenant_id_id"),
    )
    op.create_index("ix_inference_requests_provider_request", "inference_requests", ["tenant_id", "provider_request_id"])
    op.create_index("ix_inference_requests_provider_task", "inference_requests", ["tenant_id", "provider_task_id"])
    op.create_index("ix_inference_requests_tenant_status_created", "inference_requests", ["tenant_id", "status", "created_at"])

    op.create_table("generation_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("model_deployment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("modality", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("provider_task_id", sa.String(255)),
        sa.Column("request_hash", sa.String(128)),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False),
        sa.Column("error_code", sa.String(120)),
        sa.Column("sanitized_error_details", postgresql.JSONB()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("modality IN ('text', 'image', 'video', 'audio')", name="ck_generation_jobs_modality_values"),
        sa.CheckConstraint("status IN ('accepted', 'reserved', 'submitted', 'submitted_unknown', 'queued', 'running', 'storing', 'succeeded', 'failed', 'cancelled', 'expired')", name="ck_generation_jobs_status_values"),
        sa.ForeignKeyConstraint(["tenant_id", "actor_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_generation_jobs_actor_membership", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_deployment_id"], ["model_deployments.id"], name="fk_generation_jobs_model_deployment", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_generation_jobs_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", name="uq_generation_jobs_job_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_generation_jobs_tenant_id_id"),
    )
    op.create_index("ix_generation_jobs_provider_task", "generation_jobs", ["tenant_id", "provider_task_id"])
    op.create_index("ix_generation_jobs_tenant_status_created", "generation_jobs", ["tenant_id", "status", "created_at"])

    op.create_table("generation_artifacts",
        sa.Column("generation_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("storage_provider", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("kind IN ('input', 'output', 'thumbnail', 'preview')", name="ck_generation_artifacts_kind_values"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_generation_artifacts_size_nonnegative"),
        sa.CheckConstraint("status IN ('pending', 'ready', 'expired', 'deleted')", name="ck_generation_artifacts_status_values"),
        sa.ForeignKeyConstraint(["tenant_id", "generation_job_id"], ["generation_jobs.tenant_id", "generation_jobs.id"], name="fk_generation_artifacts_generation_job_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_generation_artifacts_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_generation_artifacts_tenant_id_id"),
    )
    op.create_index("ix_generation_artifacts_tenant_job", "generation_artifacts", ["tenant_id", "generation_job_id"])

    op.create_table("usage_records",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("inference_request_id", postgresql.UUID(as_uuid=True)),
        sa.Column("generation_job_id", postgresql.UUID(as_uuid=True)),
        sa.Column("model_deployment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("modality", sa.String(32), nullable=False),
        sa.Column("model_key", sa.String(200), nullable=False),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("provider_task_id", sa.String(255)),
        sa.Column("pricing_version", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("image_count", sa.BigInteger(), nullable=False),
        sa.Column("video_seconds", sa.BigInteger(), nullable=False),
        sa.Column("audio_seconds", sa.BigInteger(), nullable=False),
        sa.Column("character_count", sa.BigInteger(), nullable=False),
        sa.Column("audio_duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("video_duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("storage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("billable_units", sa.BigInteger(), nullable=False),
        sa.Column("charge_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("currency = upper(currency)", name="ck_usage_records_currency_upper"),
        sa.CheckConstraint("(inference_request_id IS NOT NULL) <> (generation_job_id IS NOT NULL)", name="ck_usage_records_exactly_one_source"),
        sa.CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND image_count >= 0 AND video_seconds >= 0 AND audio_seconds >= 0 AND storage_bytes >= 0 AND character_count >= 0 AND audio_duration_ms >= 0 AND video_duration_ms >= 0 AND billable_units >= 0 AND charge_amount_minor >= 0", name="ck_usage_records_measures_nonnegative"),
        sa.CheckConstraint("modality IN ('text', 'image', 'video', 'audio', 'embedding', 'rerank', 'multimodal')", name="ck_usage_records_modality_values"),
        sa.ForeignKeyConstraint(["tenant_id", "actor_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_usage_records_actor_membership", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "generation_job_id"], ["generation_jobs.tenant_id", "generation_jobs.id"], name="fk_usage_records_generation_job_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id", "inference_request_id"], ["inference_requests.tenant_id", "inference_requests.id"], name="fk_usage_records_inference_request_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_deployment_id"], ["model_deployments.id"], name="fk_usage_records_model_deployment", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_usage_records_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "generation_job_id", name="uq_usage_records_generation_job"),
        sa.UniqueConstraint("tenant_id", "inference_request_id", name="uq_usage_records_inference_request"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_usage_records_tenant_id_id"),
    )
    op.create_index("ix_usage_records_tenant_actor_created", "usage_records", ["tenant_id", "actor_user_id", "created_at"])
    op.create_index("ix_usage_records_tenant_created", "usage_records", ["tenant_id", "created_at"])
    op.create_index("ix_usage_records_tenant_provider_request", "usage_records", ["tenant_id", "provider_request_id"])
    op.create_index("ix_usage_records_tenant_provider_task", "usage_records", ["tenant_id", "provider_task_id"])

    op.create_table("wallet_accounts",
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("balance_minor", sa.BigInteger(), nullable=False),
        sa.Column("reserved_minor", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("balance_minor >= 0 AND reserved_minor >= 0 AND reserved_minor <= balance_minor", name="ck_wallet_accounts_balances_valid"),
        sa.CheckConstraint("currency = upper(currency)", name="ck_wallet_accounts_currency_upper"),
        sa.CheckConstraint("status IN ('active', 'frozen', 'closed')", name="ck_wallet_accounts_status_values"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_wallet_accounts_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "currency", name="uq_wallet_accounts_tenant_currency"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_wallet_accounts_tenant_id_id"),
    )
    op.create_index("ix_wallet_accounts_tenant_status", "wallet_accounts", ["tenant_id", "status"])

    op.create_table("balance_reservations",
        sa.Column("wallet_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("amount_minor > 0", name="ck_balance_reservations_amount_positive"),
        sa.CheckConstraint("status IN ('pending', 'committed', 'released', 'expired')", name="ck_balance_reservations_status_values"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_balance_reservations_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "wallet_account_id"], ["wallet_accounts.tenant_id", "wallet_accounts.id"], name="fk_balance_reservations_wallet_account_tenant", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "source_type", "source_id", name="uq_balance_reservations_source"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_balance_reservations_tenant_id_id"),
    )
    op.create_index("ix_balance_reservations_tenant_status_expiry", "balance_reservations", ["tenant_id", "status", "expires_at"])

    op.create_table("ledger_entries",
        sa.Column("wallet_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reference_type", sa.String(64), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name="ck_ledger_entries_amount_positive"),
        sa.CheckConstraint("currency = upper(currency)", name="ck_ledger_entries_currency_upper"),
        sa.CheckConstraint("entry_type IN ('credit', 'debit', 'hold', 'release', 'adjustment')", name="ck_ledger_entries_entry_type_values"),
        sa.ForeignKeyConstraint(["tenant_id", "reservation_id"], ["balance_reservations.tenant_id", "balance_reservations.id"], name="fk_ledger_entries_reservation_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_ledger_entries_tenant_id_tenants", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "wallet_account_id"], ["wallet_accounts.tenant_id", "wallet_accounts.id"], name="fk_ledger_entries_wallet_account_tenant", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_ledger_entries_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_ledger_entries_tenant_idempotency_key"),
    )
    op.create_index("ix_ledger_entries_tenant_reference", "ledger_entries", ["tenant_id", "reference_type", "reference_id"])
    op.create_index("ix_ledger_entries_tenant_wallet_created", "ledger_entries", ["tenant_id", "wallet_account_id", "created_at"])

    op.create_table("idempotency_records",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(160), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", postgresql.JSONB()),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("response_status IS NULL OR (response_status >= 100 AND response_status <= 599)", name="ck_idempotency_records_response_status"),
        sa.CheckConstraint("status IN ('processing', 'completed', 'failed')", name="ck_idempotency_records_status_values"),
        sa.ForeignKeyConstraint(["tenant_id", "actor_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_idempotency_records_actor_membership", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_idempotency_records_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "actor_user_id", "operation", "key", name="uq_idempotency_records_scope_operation_key"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_idempotency_records_tenant_id_id"),
    )
    op.create_index("ix_idempotency_records_tenant_status", "idempotency_records", ["tenant_id", "status"])

    op.create_table("outbox_events",
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("aggregate_version", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("sanitized_error_details", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("aggregate_version > 0", name="ck_outbox_events_aggregate_version_positive"),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_events_attempts_nonnegative"),
        sa.CheckConstraint("status IN ('pending', 'published', 'failed')", name="ck_outbox_events_status_values"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_outbox_events_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "aggregate_type", "aggregate_id", "aggregate_version", name="uq_outbox_events_aggregate_version"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_outbox_events_tenant_id_id"),
    )
    op.create_index("ix_outbox_events_tenant_delivery", "outbox_events", ["tenant_id", "status", "available_at"])

    op.create_table("audit_events",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(160), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("request_id", postgresql.UUID(as_uuid=True)),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("ip_address", postgresql.INET()),
        sa.Column("user_agent", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "actor_user_id"], ["memberships.tenant_id", "memberships.user_id"], name="fk_audit_events_actor_membership", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_audit_events_tenant_id_tenants", ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_audit_events_tenant_id_id"),
    )
    op.create_index("ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])
    op.create_index("ix_audit_events_tenant_resource", "audit_events", ["tenant_id", "resource_type", "resource_id"])



def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("outbox_events")
    op.drop_table("idempotency_records")
    op.drop_table("ledger_entries")
    op.drop_table("balance_reservations")
    op.drop_table("wallet_accounts")
    op.drop_table("usage_records")
    op.drop_table("generation_artifacts")
    op.drop_table("generation_jobs")
    op.drop_table("inference_requests")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("tenant_model_entitlements")
    op.drop_table("model_deployments")
    op.drop_table("provider_endpoints")
    op.drop_table("product_models")
    op.drop_table("auth_sessions")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("tenants")
