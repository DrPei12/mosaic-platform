from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.infrastructure.models import Base

EXPECTED_TABLES = {
    "tenants",
    "users",
    "memberships",
    "auth_sessions",
    "product_models",
    "provider_endpoints",
    "model_deployments",
    "model_revisions",
    "routing_policies",
    "price_versions",
    "price_bindings",
    "tenant_model_entitlements",
    "conversations",
    "messages",
    "inference_requests",
    "chat_stream_events",
    "generation_jobs",
    "generation_artifacts",
    "usage_records",
    "wallet_accounts",
    "balance_reservations",
    "ledger_entries",
    "idempotency_records",
    "outbox_events",
    "inbox_events",
    "audit_events",
}


def _constraint(table_name: str, constraint_type: type, name: str):
    table = Base.metadata.tables[table_name]
    return next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, constraint_type) and constraint.name == name
    )


def test_production_metadata_contains_all_business_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_tenant_scoped_tables_have_required_tenant_id() -> None:
    for table_name, table in Base.metadata.tables.items():
        if table_name not in {
            "tenants",
            "users",
            "product_models",
            "provider_endpoints",
            "model_deployments",
            "model_revisions",
            "routing_policies",
            "price_versions",
            "price_bindings",
        }:
            assert "tenant_id" in table.c
            assert table.c.tenant_id.nullable is False


def test_security_and_billing_constraints_are_present() -> None:
    _constraint(
        "idempotency_records",
        UniqueConstraint,
        "uq_idempotency_records_scope_operation_key",
    )
    _constraint("users", UniqueConstraint, "uq_users_email")
    _constraint("tenants", UniqueConstraint, "uq_tenants_slug")
    _constraint("wallet_accounts", CheckConstraint, "ck_wallet_accounts_balances_valid")
    _constraint("ledger_entries", CheckConstraint, "ck_ledger_entries_amount_positive")

    idempotency = Base.metadata.tables["idempotency_records"]
    unique = next(
        item
        for item in idempotency.constraints
        if isinstance(item, UniqueConstraint)
        and item.name == "uq_idempotency_records_scope_operation_key"
    )
    assert [column.name for column in unique.columns] == [
        "tenant_id",
        "actor_user_id",
        "operation",
        "key",
    ]

    provider = Base.metadata.tables["provider_endpoints"]
    assert "secret_ref" in provider.c
    assert "api_key" not in provider.c
    assert "secret" not in provider.c


def test_cross_tenant_foreign_keys_are_composite() -> None:
    deployments = Base.metadata.tables["conversations"]
    composite_fks = [
        constraint
        for constraint in deployments.constraints
        if isinstance(constraint, ForeignKeyConstraint) and len(constraint.column_keys) >= 2
    ]
    assert {constraint.name for constraint in composite_fks} == {
        "fk_conversations_created_by_membership",
        "fk_conversations_model_entitlement",
        "fk_conversations_active_inference_request_tenant",
    }
    for constraint in composite_fks:
        assert constraint.column_keys[0] == "tenant_id"
        assert [element.target_fullname.split(".")[0] for element in constraint.elements]

    active_fk = next(
        constraint
        for constraint in composite_fks
        if constraint.name == "fk_conversations_active_inference_request_tenant"
    )
    assert active_fk.column_keys == ["tenant_id", "active_inference_request_id", "id"]
    assert [element.target_fullname for element in active_fk.elements] == [
        "inference_requests.tenant_id",
        "inference_requests.id",
        "inference_requests.conversation_id",
    ]

    for table_name, constraint_name in (
        ("auth_sessions", "fk_auth_sessions_membership"),
        ("messages", "fk_messages_author_membership"),
        ("inference_requests", "fk_inference_requests_actor_membership"),
        ("generation_jobs", "fk_generation_jobs_actor_membership"),
        ("usage_records", "fk_usage_records_actor_membership"),
        ("idempotency_records", "fk_idempotency_records_actor_membership"),
        ("audit_events", "fk_audit_events_actor_membership"),
    ):
        table = Base.metadata.tables[table_name]
        assert any(
            isinstance(item, ForeignKeyConstraint)
            and item.name == constraint_name
            and item.column_keys[:1] == ["tenant_id"]
            for item in table.constraints
        )


def test_global_routing_and_tenant_entitlement_are_separate() -> None:
    for table_name in (
        "product_models",
        "provider_endpoints",
        "model_deployments",
        "model_revisions",
        "routing_policies",
        "price_versions",
        "price_bindings",
    ):
        assert "tenant_id" not in Base.metadata.tables[table_name].c
    entitlements = Base.metadata.tables["tenant_model_entitlements"]
    assert entitlements.c.tenant_id.nullable is False
    assert entitlements.c.product_model_id.nullable is False
    conversations = Base.metadata.tables["conversations"]
    assert conversations.c.product_model_id.nullable is False
    assert any(
        isinstance(item, ForeignKeyConstraint)
        and item.name == "fk_conversations_product_model"
        and item.column_keys == ["product_model_id"]
        for item in conversations.constraints
    )
    assert any(
        isinstance(item, ForeignKeyConstraint)
        and item.name == "fk_conversations_model_entitlement"
        and item.column_keys == ["tenant_id", "product_model_id"]
        for item in conversations.constraints
    )


def test_public_model_and_native_auth_fields_are_database_backed() -> None:
    product_models = Base.metadata.tables["product_models"]
    assert product_models.c.task_type.nullable is False
    assert product_models.c.pricing_summary.nullable is False
    product_ddl = str(CreateTable(product_models).compile(dialect=postgresql.dialect()))
    for task_type in ("chat", "text_to_image", "text_to_video", "image_to_video", "tts"):
        assert task_type in product_ddl

    sessions = Base.metadata.tables["auth_sessions"]
    assert sessions.c.csrf_token_hash.nullable is False
    assert "csrf_token_hash" in {
        column.name
        for constraint in sessions.constraints
        if isinstance(constraint, UniqueConstraint)
        for column in constraint.columns
    }

    users = Base.metadata.tables["users"]
    assert users.c.failed_login_count.nullable is False
    assert users.c.locked_until.nullable is True
    assert users.c.password_changed_at.nullable is False
    assert users.c.password_change_required.nullable is False
    assert users.c.credential_expires_at.nullable is True
    assert users.c.credential_used_at.nullable is True
    assert any(
        isinstance(item, CheckConstraint) and item.name == "ck_users_failed_login_count_nonnegative"
        for item in users.constraints
    )
    assert any(
        isinstance(item, CheckConstraint) and item.name == "ck_users_credential_lifecycle"
        for item in users.constraints
    )

    inference = Base.metadata.tables["inference_requests"]
    inference_ddl = str(CreateTable(inference).compile(dialect=postgresql.dialect()))
    assert "submitted_unknown" in inference_ddl
    assert "stopped" in inference_ddl


def test_job_usage_and_relay_state_constraints_are_auditable() -> None:
    jobs = Base.metadata.tables["generation_jobs"]
    jobs_ddl = str(CreateTable(jobs).compile(dialect=postgresql.dialect()))
    for status in ("accepted", "reserved", "submitted", "submitted_unknown", "storing", "expired"):
        assert status in jobs_ddl
    assert "sanitized_error_details" in jobs.c
    assert "error_message" not in jobs.c
    assert "deleted_at" in jobs.c
    assert {
        "claim_owner",
        "lease_token",
        "lease_expires_at",
        "fencing_token",
        "reconciliation_status",
        "provider_observed_status",
        "provider_observed_at",
    } <= set(jobs.c.keys())
    assert "ck_generation_jobs_lease_consistent" in jobs_ddl
    assert "ck_generation_jobs_reconciliation_status_values" in jobs_ddl

    inbox = Base.metadata.tables["inbox_events"]
    inbox_ddl = str(CreateTable(inbox).compile(dialect=postgresql.dialect()))
    assert "uq_inbox_events_provider_event" in inbox_ddl
    assert "payload_digest" in inbox.c

    artifacts = Base.metadata.tables["generation_artifacts"]
    artifacts_ddl = str(CreateTable(artifacts).compile(dialect=postgresql.dialect()))
    assert "delete_pending" in artifacts_ddl

    usage = Base.metadata.tables["usage_records"]
    assert "model_deployment_id" in usage.c
    assert "pricing_version" in usage.c
    assert "charge_amount_minor" in usage.c
    assert any(
        isinstance(item, CheckConstraint) and item.name == "ck_usage_records_exactly_one_source"
        for item in usage.constraints
    )

    ledger = Base.metadata.tables["ledger_entries"]
    assert any(
        isinstance(item, UniqueConstraint)
        and item.name == "uq_ledger_entries_tenant_idempotency_key"
        for item in ledger.constraints
    )
    reservations = Base.metadata.tables["balance_reservations"]
    assert any(
        isinstance(item, UniqueConstraint) and item.name == "uq_balance_reservations_source"
        for item in reservations.constraints
    )
    for table_name, constraint_name in (
        ("wallet_accounts", "ck_wallet_accounts_currency_upper"),
        ("usage_records", "ck_usage_records_currency_upper"),
        ("ledger_entries", "ck_ledger_entries_currency_upper"),
    ):
        table = Base.metadata.tables[table_name]
        assert any(
            isinstance(item, CheckConstraint) and item.name == constraint_name
            for item in table.constraints
        )
    outbox = Base.metadata.tables["outbox_events"]
    assert "aggregate_version" in outbox.c
    assert any(
        isinstance(item, UniqueConstraint) and item.name == "uq_outbox_events_aggregate_version"
        for item in outbox.constraints
    )


def test_postgresql_dialect_ddl_compiles_without_sqlite_assumptions() -> None:
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert "UUID" in ddl
        if table.name not in {
            "tenants",
            "users",
            "product_models",
            "provider_endpoints",
            "model_deployments",
            "model_revisions",
            "routing_policies",
            "price_versions",
            "price_bindings",
        }:
            assert "tenant_id UUID NOT NULL" in ddl
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect))


def test_versioned_catalog_facts_are_append_only_and_versioned() -> None:
    for table_name, unique_name in (
        ("model_revisions", "uq_model_revisions_product_model_version"),
        ("routing_policies", "uq_routing_policies_model_revision_version"),
        ("price_versions", "uq_price_versions_model_revision_version"),
        ("price_bindings", "uq_price_bindings_revision_deployment_price"),
    ):
        table = Base.metadata.tables[table_name]
        assert any(
            isinstance(item, UniqueConstraint) and item.name == unique_name
            for item in table.constraints
        )
        assert "updated_at" not in table.c
        assert "created_at" in table.c

    revisions = Base.metadata.tables["model_revisions"]
    assert "capability_schema" in revisions.c
    assert "capability_schema_hash" in revisions.c
    assert any(
        isinstance(item, CheckConstraint)
        and item.name == "ck_model_revisions_capability_schema_hash_sha256"
        for item in revisions.constraints
    )
    policies = Base.metadata.tables["routing_policies"]
    assert any(
        isinstance(item, CheckConstraint)
        and item.name == "ck_routing_policies_strategy_priority"
        for item in policies.constraints
    )
    bindings = Base.metadata.tables["price_bindings"]
    assert any(
        isinstance(item, CheckConstraint)
        and item.name == "ck_price_bindings_effective_window"
        for item in bindings.constraints
    )


def test_accepted_records_have_complete_legacy_safe_snapshot_contract() -> None:
    expected_columns = {
        "accepted_model_revision_id",
        "accepted_model_deployment_id",
        "accepted_routing_policy_id",
        "accepted_price_version_id",
        "accepted_capability_schema_version",
        "accepted_capability_schema_hash",
        "accepted_capability_schema",
        "accepted_input_snapshot",
        "billing_reservation_id",
    }
    for table_name in ("inference_requests", "generation_jobs"):
        table = Base.metadata.tables[table_name]
        assert expected_columns <= set(table.c.keys())
        assert all(table.c[column].nullable for column in expected_columns)
        assert any(
            isinstance(item, CheckConstraint)
            and item.name == f"ck_{table_name}_accepted_snapshot_complete"
            for item in table.constraints
        )
        foreign_keys = {
            item.name
            for item in table.constraints
            if isinstance(item, ForeignKeyConstraint)
        }
        assert {
            f"fk_{table_name}_accepted_model_revision",
            f"fk_{table_name}_accepted_model_deployment",
            f"fk_{table_name}_accepted_routing_policy",
            f"fk_{table_name}_accepted_price_version",
            f"fk_{table_name}_billing_reservation_tenant",
        } <= foreign_keys


def test_alembic_chain_has_one_production_head() -> None:
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260826_0013"]
    assert scripts.get_current_head() == "20260826_0013"


def test_provider_request_and_task_ids_are_unique_within_a_deployment() -> None:
    for table_name in ("inference_requests", "generation_jobs"):
        indexes = {index.name: index for index in Base.metadata.tables[table_name].indexes}
        for suffix, column in (
            ("provider_request", "provider_request_id"),
            ("provider_task", "provider_task_id"),
        ):
            index = indexes[f"uq_{table_name}_{suffix}"]
            assert index.unique is True
            assert [item.name for item in index.columns] == [
                "tenant_id",
                "model_deployment_id",
                column,
            ]
            assert index.dialect_options["postgresql"]["where"] is not None
