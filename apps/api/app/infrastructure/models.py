"""SQLAlchemy models for the production multi-tenant data plane.

The model layer deliberately keeps provider secrets out of the database.  A
provider endpoint stores a reference to an external secret, while the runtime
resolves that reference through the configured secret manager.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    # Explicit check names below are part of the schema contract.  Avoid a
    # constraint_name convention that would silently prefix those names.
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TenantScopedMixin:
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )


class Tenants(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
        CheckConstraint("slug = lower(slug)", name="ck_tenants_slug_lowercase"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'closed')",
            name="ck_tenants_status_values",
        ),
        Index("ix_tenants_status", "status"),
    )

    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Users(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_users_status_values",
        ),
        CheckConstraint(
            "failed_login_count >= 0",
            name="ck_users_failed_login_count_nonnegative",
        ),
        CheckConstraint(
            "(password_change_required = false AND credential_expires_at IS NULL "
            "AND credential_used_at IS NULL) OR "
            "(password_change_required = true AND credential_expires_at IS NOT NULL)",
            name="ck_users_credential_lifecycle",
        ),
        Index("ix_users_status", "status"),
        Index("ix_users_pending_credential", "password_change_required", "credential_expires_at"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    password_change_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    credential_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credential_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Memberships(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id_id"),
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
        CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'billing_viewer')",
            name="ck_memberships_role_values",
        ),
        CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'removed')",
            name="ck_memberships_status_values",
        ),
        Index("ix_memberships_tenant_status", "tenant_id", "status"),
        ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "invited_by_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_memberships_invited_by_membership",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))


class AuthSessions(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_auth_sessions_tenant_id_id"),
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        UniqueConstraint("csrf_token_hash", name="uq_auth_sessions_csrf_token_hash"),
        CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name="ck_auth_sessions_status_values",
        ),
        Index("ix_auth_sessions_user_expiry", "tenant_id", "user_id", "expires_at"),
        Index("ix_auth_sessions_expiry", "tenant_id", "expires_at"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_auth_sessions_membership",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))


class ProductModels(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "product_models"
    __table_args__ = (
        UniqueConstraint("model_key", name="uq_product_models_model_key"),
        CheckConstraint(
            "modality IN ('text', 'image', 'video', 'audio', 'embedding', 'rerank', 'multimodal')",
            name="ck_product_models_modality_values",
        ),
        CheckConstraint(
            "status IN ('active', 'hidden', 'deprecated')",
            name="ck_product_models_status_values",
        ),
        CheckConstraint(
            "task_type IN ('chat', 'text_to_image', 'text_to_video', 'image_to_video', 'tts')",
            name="ck_product_models_task_type_values",
        ),
        Index("ix_product_models_modality", "modality", "status"),
    )

    model_key: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    modality: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    pricing_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str | None] = mapped_column(Text)


class ProviderEndpoints(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "provider_endpoints"
    __table_args__ = (
        UniqueConstraint("endpoint_key", name="uq_provider_endpoints_endpoint_key"),
        CheckConstraint(
            "protocol IN ('openai_compatible', 'dashscope_http', 'dashscope_async')",
            name="ck_provider_endpoints_protocol_values",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled', 'degraded')",
            name="ck_provider_endpoints_status_values",
        ),
        CheckConstraint("timeout_ms > 0", name="ck_provider_endpoints_timeout_positive"),
        Index("ix_provider_endpoints_status", "status"),
    )

    endpoint_key: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(120), nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    secret_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=30_000)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ModelDeployments(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "model_deployments"
    __table_args__ = (
        UniqueConstraint(
            "product_model_id",
            "provider_endpoint_id",
            name="uq_model_deployments_model_endpoint",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled', 'draining')",
            name="ck_model_deployments_status_values",
        ),
        CheckConstraint("priority >= 0", name="ck_model_deployments_priority_nonnegative"),
        CheckConstraint(
            "concurrency_limit > 0",
            name="ck_model_deployments_concurrency_positive",
        ),
        Index("ix_model_deployments_model_status", "product_model_id", "status"),
        ForeignKeyConstraint(
            ["product_model_id"],
            ["product_models.id"],
            ondelete="RESTRICT",
            name="fk_model_deployments_product_model",
        ),
        ForeignKeyConstraint(
            ["provider_endpoint_id"],
            ["provider_endpoints.id"],
            ondelete="RESTRICT",
            name="fk_model_deployments_provider_endpoint",
        ),
    )

    product_model_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    provider_endpoint_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=16)
    routing_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ModelRevisions(Base, UUIDPrimaryKeyMixin):
    """Append-only model semantics and capability schema facts."""

    __tablename__ = "model_revisions"
    __table_args__ = (
        UniqueConstraint(
            "product_model_id",
            "version",
            name="uq_model_revisions_product_model_version",
        ),
        CheckConstraint("version > 0", name="ck_model_revisions_version_positive"),
        CheckConstraint(
            "capability_schema_version > 0",
            name="ck_model_revisions_capability_schema_version_positive",
        ),
        CheckConstraint(
            "jsonb_typeof(capability_schema) = 'object'",
            name="ck_model_revisions_capability_schema_object",
        ),
        CheckConstraint(
            "capability_schema_hash ~ '^[0-9a-f]{64}$'",
            name="ck_model_revisions_capability_schema_hash_sha256",
        ),
        Index("ix_model_revisions_product_model_version", "product_model_id", "version"),
        ForeignKeyConstraint(
            ["product_model_id"],
            ["product_models.id"],
            ondelete="RESTRICT",
            name="fk_model_revisions_product_model",
        ),
    )

    product_model_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    model_key: Mapped[str] = mapped_column(String(160), nullable=False)
    modality: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    capability_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    capability_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    capability_schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RoutingPolicies(Base, UUIDPrimaryKeyMixin):
    """Append-only routing policy facts; this milestone supports priority only."""

    __tablename__ = "routing_policies"
    __table_args__ = (
        UniqueConstraint(
            "model_revision_id",
            "version",
            name="uq_routing_policies_model_revision_version",
        ),
        UniqueConstraint(
            "policy_key",
            "version",
            name="uq_routing_policies_policy_key_version",
        ),
        CheckConstraint("version > 0", name="ck_routing_policies_version_positive"),
        CheckConstraint(
            "strategy = 'priority'",
            name="ck_routing_policies_strategy_priority",
        ),
        CheckConstraint(
            "jsonb_typeof(config) = 'object'",
            name="ck_routing_policies_config_object",
        ),
        Index("ix_routing_policies_revision_version", "model_revision_id", "version"),
        ForeignKeyConstraint(
            ["model_revision_id"],
            ["model_revisions.id"],
            ondelete="RESTRICT",
            name="fk_routing_policies_model_revision",
        ),
    )

    model_revision_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    policy_key: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="priority")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PriceVersions(Base, UUIDPrimaryKeyMixin):
    """Append-only customer price facts interpreted by the billing tariff."""

    __tablename__ = "price_versions"
    __table_args__ = (
        UniqueConstraint(
            "model_revision_id",
            "version",
            name="uq_price_versions_model_revision_version",
        ),
        UniqueConstraint(
            "price_key",
            "version",
            name="uq_price_versions_price_key_version",
        ),
        CheckConstraint("version > 0", name="ck_price_versions_version_positive"),
        CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency) "
            "AND currency ~ '^[A-Z]{3}$'",
            name="ck_price_versions_currency_upper",
        ),
        CheckConstraint(
            "jsonb_typeof(pricing) = 'object'",
            name="ck_price_versions_pricing_object",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_price_versions_effective_window",
        ),
        Index("ix_price_versions_revision_effective", "model_revision_id", "effective_from"),
        ForeignKeyConstraint(
            ["model_revision_id"],
            ["model_revisions.id"],
            ondelete="RESTRICT",
            name="fk_price_versions_model_revision",
        ),
    )

    model_revision_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    price_key: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    pricing: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PriceBindings(Base, UUIDPrimaryKeyMixin):
    """Append-only binding of a model revision and deployment to a price fact."""

    __tablename__ = "price_bindings"
    __table_args__ = (
        UniqueConstraint(
            "model_revision_id",
            "model_deployment_id",
            "price_version_id",
            name="uq_price_bindings_revision_deployment_price",
        ),
        UniqueConstraint(
            "model_revision_id",
            "model_deployment_id",
            "effective_from",
            name="uq_price_bindings_revision_deployment_start",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_price_bindings_effective_window",
        ),
        Index(
            "ix_price_bindings_revision_deployment_effective",
            "model_revision_id",
            "model_deployment_id",
            "effective_from",
        ),
        ForeignKeyConstraint(
            ["model_revision_id"],
            ["model_revisions.id"],
            ondelete="RESTRICT",
            name="fk_price_bindings_model_revision",
        ),
        ForeignKeyConstraint(
            ["model_deployment_id"],
            ["model_deployments.id"],
            ondelete="RESTRICT",
            name="fk_price_bindings_model_deployment",
        ),
        ForeignKeyConstraint(
            ["price_version_id"],
            ["price_versions.id"],
            ondelete="RESTRICT",
            name="fk_price_bindings_price_version",
        ),
    )

    model_revision_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    model_deployment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    price_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TenantModelEntitlements(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """Tenant access to a platform-global product model."""

    __tablename__ = "tenant_model_entitlements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tenant_model_entitlements_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "product_model_id", name="uq_tenant_model_entitlements_tenant_model"
        ),
        Index(
            "ix_tenant_model_entitlements_tenant_enabled",
            "tenant_id",
            "enabled",
        ),
        Index(
            "ix_tenant_model_entitlements_model_enabled",
            "product_model_id",
            "enabled",
        ),
        ForeignKeyConstraint(
            ["product_model_id"],
            ["product_models.id"],
            ondelete="RESTRICT",
            name="fk_tenant_model_entitlements_product_model",
        ),
    )

    product_model_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Conversations(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id_id"),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_conversations_status_values",
        ),
        CheckConstraint("version >= 0", name="ck_conversations_version_nonnegative"),
        Index("ix_conversations_tenant_updated", "tenant_id", "updated_at"),
        Index("ix_conversations_tenant_model", "tenant_id", "product_model_id"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_conversations_created_by_membership",
        ),
        ForeignKeyConstraint(
            ["product_model_id"],
            ["product_models.id"],
            ondelete="RESTRICT",
            name="fk_conversations_product_model",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_model_id"],
            ["tenant_model_entitlements.tenant_id", "tenant_model_entitlements.product_model_id"],
            ondelete="RESTRICT",
            name="fk_conversations_model_entitlement",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "active_inference_request_id", "id"],
            ["inference_requests.tenant_id", "inference_requests.id", "inference_requests.conversation_id"],
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_conversations_active_inference_request_tenant",
        ),
    )

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_model_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active_inference_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )


class Messages(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_messages_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "conversation_id", "sequence_no", name="uq_messages_conversation_sequence"
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "conversation_id",
            name="uq_messages_tenant_id_conversation",
        ),
        CheckConstraint(
            "role IN ('system', 'user', 'assistant', 'tool')",
            name="ck_messages_role_values",
        ),
        CheckConstraint(
            "status IN ('accepted', 'streaming', 'completed', 'failed', 'stopped')",
            name="ck_messages_status_values",
        ),
        CheckConstraint(
            "role NOT IN ('user', 'assistant') OR ("
            "jsonb_typeof(content) = 'object' AND content ? 'type' "
            "AND content->>'type' = 'text' AND content ? 'text' "
            "AND jsonb_typeof(content->'text') = 'string')",
            name="ck_messages_content_text_object",
        ),
        Index(
            "ix_messages_tenant_conversation_sequence",
            "tenant_id",
            "conversation_id",
            "sequence_no",
        ),
        Index("ix_messages_tenant_request", "tenant_id", "request_id"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="RESTRICT",
            name="fk_messages_conversation_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "author_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_messages_author_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "request_id", "conversation_id", "id"],
            [
                "inference_requests.tenant_id",
                "inference_requests.id",
                "inference_requests.conversation_id",
                "inference_requests.message_id",
            ],
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_messages_inference_request_tenant",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    legacy_content: Mapped[Any | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted")
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    provider_model_id: Mapped[str | None] = mapped_column(String(200))


class InferenceRequests(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "inference_requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_inference_requests_tenant_id_id"),
        UniqueConstraint("request_id", name="uq_inference_requests_request_id"),
        CheckConstraint(
            "status IN ('queued', 'running', 'submitted_unknown', 'stopped', "
            "'stop_requested', 'succeeded', 'failed', 'cancelled')",
            name="ck_inference_requests_status_values",
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name="ck_inference_requests_tokens_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "conversation_id",
            name="uq_inference_requests_tenant_id_conversation",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "conversation_id",
            "message_id",
            name="uq_inference_requests_tenant_id_conversation_message",
        ),
        CheckConstraint("request_hash <> ''", name="ck_inference_requests_request_hash_nonempty"),
        CheckConstraint(
            "last_event_sequence >= -1",
            name="ck_inference_requests_last_event_sequence_floor",
        ),
        CheckConstraint(
            "message_id IS NULL OR conversation_id IS NOT NULL",
            name="ck_inference_requests_message_requires_conversation",
        ),
        CheckConstraint(
            "(accepted_model_revision_id IS NULL AND "
            "accepted_model_deployment_id IS NULL AND accepted_routing_policy_id IS NULL AND "
            "accepted_price_version_id IS NULL AND accepted_capability_schema_version IS NULL "
            "AND accepted_capability_schema_hash IS NULL AND accepted_capability_schema IS NULL "
            "AND accepted_input_snapshot IS NULL) OR ("
            "accepted_model_revision_id IS NOT NULL AND "
            "accepted_model_deployment_id IS NOT NULL AND accepted_routing_policy_id IS NOT NULL AND "
            "accepted_price_version_id IS NOT NULL AND accepted_capability_schema_version > 0 AND "
            "accepted_capability_schema_hash ~ '^[0-9a-f]{64}$' AND "
            "jsonb_typeof(accepted_capability_schema) = 'object' AND "
            "jsonb_typeof(accepted_input_snapshot) = 'object' AND "
            "accepted_model_deployment_id = model_deployment_id)",
            name="ck_inference_requests_accepted_snapshot_complete",
        ),
        Index("ix_inference_requests_tenant_status_created", "tenant_id", "status", "created_at"),
        Index(
            "ix_inference_requests_tenant_accepted_revision",
            "tenant_id",
            "accepted_model_revision_id",
        ),
        Index(
            "ix_inference_requests_tenant_billing_reservation",
            "tenant_id",
            "billing_reservation_id",
        ),
        Index("ix_inference_requests_provider_request", "tenant_id", "provider_request_id"),
        Index("ix_inference_requests_provider_task", "tenant_id", "provider_task_id"),
        Index(
            "uq_inference_requests_provider_request",
            "tenant_id",
            "model_deployment_id",
            "provider_request_id",
            unique=True,
            postgresql_where=text("provider_request_id IS NOT NULL"),
        ),
        Index(
            "uq_inference_requests_provider_task",
            "tenant_id",
            "model_deployment_id",
            "provider_task_id",
            unique=True,
            postgresql_where=text("provider_task_id IS NOT NULL"),
        ),
        Index(
            "uq_inference_requests_active_conversation",
            "tenant_id",
            "conversation_id",
            unique=True,
            postgresql_where=text(
                "conversation_id IS NOT NULL AND status IN "
                "('queued', 'running', 'submitted_unknown', 'stop_requested')"
            ),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="RESTRICT",
            name="fk_inference_requests_conversation_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "message_id", "conversation_id"],
            ["messages.tenant_id", "messages.id", "messages.conversation_id"],
            ondelete="RESTRICT",
            name="fk_inference_requests_message_tenant",
        ),
        ForeignKeyConstraint(
            ["model_deployment_id"],
            ["model_deployments.id"],
            ondelete="RESTRICT",
            name="fk_inference_requests_model_deployment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_inference_requests_actor_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_request_id"],
            ["inference_requests.tenant_id", "inference_requests.id"],
            ondelete="RESTRICT",
            name="fk_inference_requests_parent_request_tenant",
        ),
        ForeignKeyConstraint(
            ["accepted_model_revision_id"],
            ["model_revisions.id"],
            ondelete="RESTRICT",
            name="fk_inference_requests_accepted_model_revision",
        ),
        ForeignKeyConstraint(
            ["accepted_model_deployment_id"],
            ["model_deployments.id"],
            ondelete="RESTRICT",
            name="fk_inference_requests_accepted_model_deployment",
        ),
        ForeignKeyConstraint(
            ["accepted_routing_policy_id"],
            ["routing_policies.id"],
            ondelete="RESTRICT",
            name="fk_inference_requests_accepted_routing_policy",
        ),
        ForeignKeyConstraint(
            ["accepted_price_version_id"],
            ["price_versions.id"],
            ondelete="RESTRICT",
            name="fk_inference_requests_accepted_price_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "billing_reservation_id"],
            ["balance_reservations.tenant_id", "balance_reservations.id"],
            ondelete="RESTRICT",
            name="fk_inference_requests_billing_reservation_tenant",
        ),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    model_deployment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    accepted_model_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    accepted_model_deployment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    accepted_routing_policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    accepted_price_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    billing_reservation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    accepted_capability_schema_version: Mapped[int | None] = mapped_column(Integer)
    accepted_capability_schema_hash: Mapped[str | None] = mapped_column(String(64))
    accepted_capability_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    accepted_input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    provider_task_id: Mapped[str | None] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_sequence: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=-1,
        server_default=text("-1"),
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_reason: Mapped[str | None] = mapped_column(String(160))
    sanitized_error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parent_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))


class ChatStreamEvents(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """Durable, replayable SSE events for one text inference request."""

    __tablename__ = "chat_stream_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_chat_stream_events_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "inference_request_id",
            "sequence_no",
            name="uq_chat_stream_events_request_sequence",
        ),
        CheckConstraint(
            "sequence_no >= 0",
            name="ck_chat_stream_events_sequence_nonnegative",
        ),
        CheckConstraint(
            "event_type IN ('started', 'delta', 'completed', 'stopped', 'failed')",
            name="ck_chat_stream_events_event_type_values",
        ),
        Index(
            "ix_chat_stream_events_tenant_request_sequence",
            "tenant_id",
            "inference_request_id",
            "sequence_no",
        ),
        Index(
            "uq_chat_stream_events_terminal",
            "tenant_id",
            "inference_request_id",
            unique=True,
            postgresql_where=text("event_type IN ('completed', 'stopped', 'failed')"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inference_request_id"],
            ["inference_requests.tenant_id", "inference_requests.id"],
            ondelete="RESTRICT",
            name="fk_chat_stream_events_inference_request_tenant",
        ),
    )

    inference_request_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GenerationJobs(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_generation_jobs_tenant_id_id"),
        UniqueConstraint("job_id", name="uq_generation_jobs_job_id"),
        CheckConstraint(
            "modality IN ('text', 'image', 'video', 'audio')",
            name="ck_generation_jobs_modality_values",
        ),
        CheckConstraint(
            "status IN ('accepted', 'reserved', 'submitted', 'submitted_unknown', "
            "'queued', 'running', 'storing', 'succeeded', 'failed', 'cancelled', 'expired')",
            name="ck_generation_jobs_status_values",
        ),
        CheckConstraint("fencing_token >= 0", name="ck_generation_jobs_fencing_nonnegative"),
        CheckConstraint(
            "(claim_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(claim_owner IS NOT NULL AND claim_owner <> '' AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name="ck_generation_jobs_lease_consistent",
        ),
        CheckConstraint(
            "reconciliation_status IN ('not_required', 'pending', 'resolved', 'disputed')",
            name="ck_generation_jobs_reconciliation_status_values",
        ),
        CheckConstraint(
            "(accepted_model_revision_id IS NULL AND "
            "accepted_model_deployment_id IS NULL AND accepted_routing_policy_id IS NULL AND "
            "accepted_price_version_id IS NULL AND accepted_capability_schema_version IS NULL "
            "AND accepted_capability_schema_hash IS NULL AND accepted_capability_schema IS NULL "
            "AND accepted_input_snapshot IS NULL) OR ("
            "accepted_model_revision_id IS NOT NULL AND "
            "accepted_model_deployment_id IS NOT NULL AND accepted_routing_policy_id IS NOT NULL AND "
            "accepted_price_version_id IS NOT NULL AND accepted_capability_schema_version > 0 AND "
            "accepted_capability_schema_hash ~ '^[0-9a-f]{64}$' AND "
            "jsonb_typeof(accepted_capability_schema) = 'object' AND "
            "jsonb_typeof(accepted_input_snapshot) = 'object' AND "
            "accepted_model_deployment_id = model_deployment_id)",
            name="ck_generation_jobs_accepted_snapshot_complete",
        ),
        Index("ix_generation_jobs_tenant_status_created", "tenant_id", "status", "created_at"),
        Index(
            "ix_generation_jobs_tenant_accepted_revision",
            "tenant_id",
            "accepted_model_revision_id",
        ),
        Index(
            "ix_generation_jobs_tenant_billing_reservation",
            "tenant_id",
            "billing_reservation_id",
        ),
        Index("ix_generation_jobs_provider_task", "tenant_id", "provider_task_id"),
        Index(
            "ix_generation_jobs_tenant_actor_visible",
            "tenant_id",
            "actor_user_id",
            "deleted_at",
            "created_at",
        ),
        Index(
            "ix_generation_jobs_recovery_claim",
            "status",
            "reconciliation_status",
            "lease_expires_at",
            "updated_at",
        ),
        Index(
            "uq_generation_jobs_provider_request",
            "tenant_id",
            "model_deployment_id",
            "provider_request_id",
            unique=True,
            postgresql_where=text("provider_request_id IS NOT NULL"),
        ),
        Index(
            "uq_generation_jobs_provider_task",
            "tenant_id",
            "model_deployment_id",
            "provider_task_id",
            unique=True,
            postgresql_where=text("provider_task_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["model_deployment_id"],
            ["model_deployments.id"],
            ondelete="RESTRICT",
            name="fk_generation_jobs_model_deployment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_generation_jobs_actor_membership",
        ),
        ForeignKeyConstraint(
            ["accepted_model_revision_id"],
            ["model_revisions.id"],
            ondelete="RESTRICT",
            name="fk_generation_jobs_accepted_model_revision",
        ),
        ForeignKeyConstraint(
            ["accepted_model_deployment_id"],
            ["model_deployments.id"],
            ondelete="RESTRICT",
            name="fk_generation_jobs_accepted_model_deployment",
        ),
        ForeignKeyConstraint(
            ["accepted_routing_policy_id"],
            ["routing_policies.id"],
            ondelete="RESTRICT",
            name="fk_generation_jobs_accepted_routing_policy",
        ),
        ForeignKeyConstraint(
            ["accepted_price_version_id"],
            ["price_versions.id"],
            ondelete="RESTRICT",
            name="fk_generation_jobs_accepted_price_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "billing_reservation_id"],
            ["balance_reservations.tenant_id", "balance_reservations.id"],
            ondelete="RESTRICT",
            name="fk_generation_jobs_billing_reservation_tenant",
        ),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    model_deployment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    accepted_model_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    accepted_model_deployment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    accepted_routing_policy_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    accepted_price_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    billing_reservation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    accepted_capability_schema_version: Mapped[int | None] = mapped_column(Integer)
    accepted_capability_schema_hash: Mapped[str | None] = mapped_column(String(64))
    accepted_capability_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    accepted_input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    modality: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    provider_task_id: Mapped[str | None] = mapped_column(String(255))
    request_hash: Mapped[str | None] = mapped_column(String(128))
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(120))
    sanitized_error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    claim_owner: Mapped[str | None] = mapped_column(String(200))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fencing_token: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    reconciliation_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="not_required",
        server_default=text("'not_required'"),
    )
    provider_observed_status: Mapped[str | None] = mapped_column(String(64))
    provider_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GenerationArtifacts(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "generation_artifacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_generation_artifacts_tenant_id_id"),
        CheckConstraint(
            "kind IN ('input', 'output', 'thumbnail', 'preview')",
            name="ck_generation_artifacts_kind_values",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'expired', 'delete_pending', 'deleted')",
            name="ck_generation_artifacts_status_values",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_generation_artifacts_size_nonnegative"),
        Index("ix_generation_artifacts_tenant_job", "tenant_id", "generation_job_id"),
        ForeignKeyConstraint(
            ["tenant_id", "generation_job_id"],
            ["generation_jobs.tenant_id", "generation_jobs.id"],
            ondelete="RESTRICT",
            name="fk_generation_artifacts_generation_job_tenant",
        ),
    )

    generation_job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    storage_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageRecords(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_usage_records_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "inference_request_id", name="uq_usage_records_inference_request"
        ),
        UniqueConstraint("tenant_id", "generation_job_id", name="uq_usage_records_generation_job"),
        CheckConstraint(
            "modality IN ('text', 'image', 'video', 'audio', 'embedding', 'rerank', 'multimodal')",
            name="ck_usage_records_modality_values",
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND image_count >= 0 "
            "AND video_seconds >= 0 AND audio_seconds >= 0 AND storage_bytes >= 0 "
            "AND character_count >= 0 AND audio_duration_ms >= 0 AND video_duration_ms >= 0 "
            "AND billable_units >= 0 AND charge_amount_minor >= 0",
            name="ck_usage_records_measures_nonnegative",
        ),
        CheckConstraint(
            "(inference_request_id IS NOT NULL) <> (generation_job_id IS NOT NULL)",
            name="ck_usage_records_exactly_one_source",
        ),
        CheckConstraint("currency = upper(currency)", name="ck_usage_records_currency_upper"),
        Index("ix_usage_records_tenant_created", "tenant_id", "created_at"),
        Index("ix_usage_records_tenant_actor_created", "tenant_id", "actor_user_id", "created_at"),
        Index("ix_usage_records_tenant_provider_request", "tenant_id", "provider_request_id"),
        Index("ix_usage_records_tenant_provider_task", "tenant_id", "provider_task_id"),
        ForeignKeyConstraint(
            ["model_deployment_id"],
            ["model_deployments.id"],
            ondelete="RESTRICT",
            name="fk_usage_records_model_deployment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inference_request_id"],
            ["inference_requests.tenant_id", "inference_requests.id"],
            ondelete="RESTRICT",
            name="fk_usage_records_inference_request_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "generation_job_id"],
            ["generation_jobs.tenant_id", "generation_jobs.id"],
            ondelete="RESTRICT",
            name="fk_usage_records_generation_job_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_usage_records_actor_membership",
        ),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    inference_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    generation_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    model_deployment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    modality: Mapped[str] = mapped_column(String(32), nullable=False)
    model_key: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    provider_task_id: Mapped[str | None] = mapped_column(String(255))
    pricing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    image_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    audio_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    character_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    audio_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    billable_units: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    charge_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class WalletAccounts(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "wallet_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_wallet_accounts_tenant_id_id"),
        UniqueConstraint("tenant_id", "currency", name="uq_wallet_accounts_tenant_currency"),
        CheckConstraint(
            "status IN ('active', 'frozen', 'closed')", name="ck_wallet_accounts_status_values"
        ),
        CheckConstraint(
            "balance_minor >= 0 AND reserved_minor >= 0 AND reserved_minor <= balance_minor",
            name="ck_wallet_accounts_balances_valid",
        ),
        CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency) "
            "AND currency ~ '^[A-Z]{3}$'",
            name="ck_wallet_accounts_currency_upper",
        ),
        CheckConstraint("version >= 0", name="ck_wallet_accounts_version_nonnegative"),
        Index("ix_wallet_accounts_tenant_status", "tenant_id", "status"),
    )

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class BalanceReservations(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "balance_reservations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_balance_reservations_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "source_type",
            "source_id",
            name="uq_balance_reservations_source",
        ),
        CheckConstraint(
            "status IN ('pending', 'committed', 'released', 'expired')",
            name="ck_balance_reservations_status_values",
        ),
        CheckConstraint("amount_minor > 0", name="ck_balance_reservations_amount_positive"),
        CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency) "
            "AND currency ~ '^[A-Z]{3}$'",
            name="ck_balance_reservations_currency_upper",
        ),
        CheckConstraint(
            "captured_amount_minor IS NULL OR "
            "(captured_amount_minor >= 0 AND captured_amount_minor <= amount_minor)",
            name="ck_balance_reservations_captured_amount_valid",
        ),
        CheckConstraint(
            "(status = 'committed' AND captured_amount_minor IS NOT NULL) OR "
            "(status <> 'committed' AND captured_amount_minor IS NULL)",
            name="ck_balance_reservations_capture_status_consistent",
        ),
        Index("ix_balance_reservations_tenant_status_expiry", "tenant_id", "status", "expires_at"),
        ForeignKeyConstraint(
            ["tenant_id", "wallet_account_id"],
            ["wallet_accounts.tenant_id", "wallet_accounts.id"],
            ondelete="RESTRICT",
            name="fk_balance_reservations_wallet_account_tenant",
        ),
    )

    wallet_account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LedgerEntries(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    """Immutable wallet journal rows; corrections are compensating entries."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_ledger_entries_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_ledger_entries_tenant_idempotency_key"
        ),
        CheckConstraint(
            "entry_type IN ('credit', 'debit', 'hold', 'release', 'adjustment')",
            name="ck_ledger_entries_entry_type_values",
        ),
        CheckConstraint("amount_minor > 0", name="ck_ledger_entries_amount_positive"),
        CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency) "
            "AND currency ~ '^[A-Z]{3}$'",
            name="ck_ledger_entries_currency_upper",
        ),
        Index(
            "ix_ledger_entries_tenant_wallet_created",
            "tenant_id",
            "wallet_account_id",
            "created_at",
        ),
        Index("ix_ledger_entries_tenant_reference", "tenant_id", "reference_type", "reference_id"),
        ForeignKeyConstraint(
            ["tenant_id", "wallet_account_id"],
            ["wallet_accounts.tenant_id", "wallet_accounts.id"],
            ondelete="RESTRICT",
            name="fk_ledger_entries_wallet_account_tenant",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            ["balance_reservations.tenant_id", "balance_reservations.id"],
            ondelete="RESTRICT",
            name="fk_ledger_entries_reservation_tenant",
        ),
    )

    wallet_account_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdempotencyRecords(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_idempotency_records_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "actor_user_id",
            "operation",
            "key",
            name="uq_idempotency_records_scope_operation_key",
        ),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_idempotency_records_status_values",
        ),
        CheckConstraint(
            "response_status IS NULL OR (response_status >= 100 AND response_status <= 599)",
            name="ck_idempotency_records_response_status",
        ),
        Index("ix_idempotency_records_tenant_status", "tenant_id", "status"),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_idempotency_records_actor_membership",
        ),
    )

    actor_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(160), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvents(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_outbox_events_tenant_id_id"),
        CheckConstraint(
            "status IN ('pending', 'published', 'failed')",
            name="ck_outbox_events_status_values",
        ),
        CheckConstraint("attempts >= 0", name="ck_outbox_events_attempts_nonnegative"),
        CheckConstraint(
            "aggregate_version > 0", name="ck_outbox_events_aggregate_version_positive"
        ),
        CheckConstraint(
            "(claim_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(claim_owner IS NOT NULL AND claim_owner <> '' AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name="ck_outbox_events_lease_consistent",
        ),
        UniqueConstraint(
            "tenant_id",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            name="uq_outbox_events_aggregate_version",
        ),
        Index("ix_outbox_events_tenant_delivery", "tenant_id", "status", "available_at"),
        Index(
            "ix_outbox_events_relay_claim",
            "status",
            "event_type",
            "available_at",
            "lease_expires_at",
        ),
    )

    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sanitized_error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    claim_owner: Mapped[str | None] = mapped_column(String(200))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InboxEvents(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "inbox_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_inbox_events_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "provider_name",
            "event_key",
            name="uq_inbox_events_provider_event",
        ),
        CheckConstraint(
            "status IN ('received', 'processed', 'rejected')",
            name="ck_inbox_events_status_values",
        ),
        CheckConstraint(
            "payload_digest ~ '^[0-9a-f]{64}$'",
            name="ck_inbox_events_payload_digest_sha256",
        ),
        Index("ix_inbox_events_tenant_status_created", "tenant_id", "status", "created_at"),
    )

    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvents(Base, UUIDPrimaryKeyMixin, TenantScopedMixin):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_audit_events_tenant_id_id"),
        Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_events_tenant_resource", "tenant_id", "resource_type", "resource_id"),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["memberships.tenant_id", "memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_audit_events_actor_membership",
        ),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Singular aliases keep the domain names readable for callers while the
# plural class names remain consistent with the legacy model module.
ModelRevision = ModelRevisions
RoutingPolicy = RoutingPolicies
PriceVersion = PriceVersions
PriceBinding = PriceBindings


__all__ = [
    "AuditEvents",
    "AuthSessions",
    "BalanceReservations",
    "Base",
    "ChatStreamEvents",
    "Conversations",
    "GenerationArtifacts",
    "GenerationJobs",
    "IdempotencyRecords",
    "InboxEvents",
    "InferenceRequests",
    "LedgerEntries",
    "Memberships",
    "Messages",
    "ModelDeployments",
    "ModelRevision",
    "ModelRevisions",
    "OutboxEvents",
    "PriceBinding",
    "PriceBindings",
    "PriceVersion",
    "PriceVersions",
    "ProductModels",
    "ProviderEndpoints",
    "RoutingPolicies",
    "RoutingPolicy",
    "TenantModelEntitlements",
    "Tenants",
    "UsageRecords",
    "Users",
    "WalletAccounts",
]
