"""Add append-only catalog facts and accepted decision snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0008"
down_revision: str | None = "20260825_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SNAPSHOT_COLUMNS = (
    "accepted_model_revision_id",
    "accepted_model_deployment_id",
    "accepted_routing_policy_id",
    "accepted_price_version_id",
    "accepted_capability_schema_version",
    "accepted_capability_schema_hash",
    "accepted_capability_schema",
    "accepted_input_snapshot",
)


def _create_immutable_fact_guards() -> None:
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION reject_versioned_catalog_fact_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'immutable catalog fact % cannot be changed', TG_TABLE_NAME;
            END;
            $$
            """
        )
    )
    for table_name in (
        "model_revisions",
        "routing_policies",
        "price_versions",
        "price_bindings",
    ):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table_name}_immutable
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION reject_versioned_catalog_fact_mutation()
                """
            )
        )


def _create_price_overlap_guard() -> None:
    # The advisory lock makes the trigger deterministic for concurrent inserts
    # sharing one revision/deployment without requiring btree_gist privileges.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION reject_overlapping_price_binding()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                PERFORM pg_advisory_xact_lock(
                    hashtextextended(
                        NEW.model_revision_id::text || ':' || NEW.model_deployment_id::text,
                        0
                    )
                );
                IF EXISTS (
                    SELECT 1
                    FROM price_bindings AS existing
                    WHERE existing.model_revision_id = NEW.model_revision_id
                      AND existing.model_deployment_id = NEW.model_deployment_id
                      AND existing.id <> NEW.id
                      AND tstzrange(
                            existing.effective_from,
                            COALESCE(existing.effective_to, 'infinity'::timestamptz),
                            '[)'
                          ) && tstzrange(
                            NEW.effective_from,
                            COALESCE(NEW.effective_to, 'infinity'::timestamptz),
                            '[)'
                          )
                ) THEN
                    RAISE EXCEPTION
                        'overlapping price binding for revision % and deployment %',
                        NEW.model_revision_id,
                        NEW.model_deployment_id;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_price_bindings_no_overlap
            BEFORE INSERT ON price_bindings
            FOR EACH ROW EXECUTE FUNCTION reject_overlapping_price_binding()
            """
        )
    )


def _create_snapshot_guard() -> None:
    comparisons = " OR ".join(
        f"OLD.{column} IS DISTINCT FROM NEW.{column}" for column in _SNAPSHOT_COLUMNS
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION reject_accepted_snapshot_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF {comparisons} THEN
                    RAISE EXCEPTION
                        'accepted decision snapshot on % is immutable', TG_TABLE_NAME;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    for table_name in ("inference_requests", "generation_jobs"):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table_name}_accepted_snapshot_immutable
                BEFORE UPDATE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION reject_accepted_snapshot_mutation()
                """
            )
        )


def upgrade() -> None:
    op.create_table(
        "model_revisions",
        sa.Column("product_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_key", sa.String(160), nullable=False),
        sa.Column("modality", sa.String(32), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("capability_schema_version", sa.Integer(), nullable=False),
        sa.Column("capability_schema", postgresql.JSONB(), nullable=False),
        sa.Column("capability_schema_hash", sa.String(64), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("version > 0", name="ck_model_revisions_version_positive"),
        sa.CheckConstraint(
            "capability_schema_version > 0",
            name="ck_model_revisions_capability_schema_version_positive",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(capability_schema) = 'object'",
            name="ck_model_revisions_capability_schema_object",
        ),
        sa.CheckConstraint(
            "capability_schema_hash ~ '^[0-9a-f]{64}$'",
            name="ck_model_revisions_capability_schema_hash_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["product_model_id"],
            ["product_models.id"],
            name="fk_model_revisions_product_model",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "product_model_id",
            "version",
            name="uq_model_revisions_product_model_version",
        ),
    )
    op.create_index(
        "ix_model_revisions_product_model_version",
        "model_revisions",
        ["product_model_id", "version"],
    )

    op.create_table(
        "routing_policies",
        sa.Column("model_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_key", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(32), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("version > 0", name="ck_routing_policies_version_positive"),
        sa.CheckConstraint(
            "strategy = 'priority'",
            name="ck_routing_policies_strategy_priority",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(config) = 'object'",
            name="ck_routing_policies_config_object",
        ),
        sa.ForeignKeyConstraint(
            ["model_revision_id"],
            ["model_revisions.id"],
            name="fk_routing_policies_model_revision",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "model_revision_id",
            "version",
            name="uq_routing_policies_model_revision_version",
        ),
        sa.UniqueConstraint(
            "policy_key",
            "version",
            name="uq_routing_policies_policy_key_version",
        ),
    )
    op.create_index(
        "ix_routing_policies_revision_version",
        "routing_policies",
        ["model_revision_id", "version"],
    )

    op.create_table(
        "price_versions",
        sa.Column("model_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_key", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("pricing", postgresql.JSONB(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("version > 0", name="ck_price_versions_version_positive"),
        sa.CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency) "
            "AND currency ~ '^[A-Z]{3}$'",
            name="ck_price_versions_currency_upper",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(pricing) = 'object'",
            name="ck_price_versions_pricing_object",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_price_versions_effective_window",
        ),
        sa.ForeignKeyConstraint(
            ["model_revision_id"],
            ["model_revisions.id"],
            name="fk_price_versions_model_revision",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "model_revision_id",
            "version",
            name="uq_price_versions_model_revision_version",
        ),
        sa.UniqueConstraint(
            "price_key",
            "version",
            name="uq_price_versions_price_key_version",
        ),
    )
    op.create_index(
        "ix_price_versions_revision_effective",
        "price_versions",
        ["model_revision_id", "effective_from"],
    )

    op.create_table(
        "price_bindings",
        sa.Column("model_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_deployment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_price_bindings_effective_window",
        ),
        sa.ForeignKeyConstraint(
            ["model_revision_id"],
            ["model_revisions.id"],
            name="fk_price_bindings_model_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_deployment_id"],
            ["model_deployments.id"],
            name="fk_price_bindings_model_deployment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["price_version_id"],
            ["price_versions.id"],
            name="fk_price_bindings_price_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "model_revision_id",
            "model_deployment_id",
            "price_version_id",
            name="uq_price_bindings_revision_deployment_price",
        ),
        sa.UniqueConstraint(
            "model_revision_id",
            "model_deployment_id",
            "effective_from",
            name="uq_price_bindings_revision_deployment_start",
        ),
    )
    op.create_index(
        "ix_price_bindings_revision_deployment_effective",
        "price_bindings",
        ["model_revision_id", "model_deployment_id", "effective_from"],
    )

    for table_name in ("inference_requests", "generation_jobs"):
        op.add_column(
            table_name,
            sa.Column(
                "accepted_model_revision_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.add_column(
            table_name,
            sa.Column(
                "accepted_model_deployment_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.add_column(
            table_name,
            sa.Column(
                "accepted_routing_policy_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.add_column(
            table_name,
            sa.Column(
                "accepted_price_version_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )
        op.add_column(
            table_name,
            sa.Column("accepted_capability_schema_version", sa.Integer(), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("accepted_capability_schema_hash", sa.String(64), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("accepted_capability_schema", postgresql.JSONB(), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("accepted_input_snapshot", postgresql.JSONB(), nullable=True),
        )
        op.create_check_constraint(
            f"ck_{table_name}_accepted_snapshot_complete",
            table_name,
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
        )
        op.create_index(
            f"ix_{table_name}_tenant_accepted_revision",
            table_name,
            ["tenant_id", "accepted_model_revision_id"],
        )
        for column, target_table in (
            ("accepted_model_revision_id", "model_revisions"),
            ("accepted_model_deployment_id", "model_deployments"),
            ("accepted_routing_policy_id", "routing_policies"),
            ("accepted_price_version_id", "price_versions"),
        ):
            op.create_foreign_key(
                f"fk_{table_name}_{column}",
                table_name,
                target_table,
                [column],
                ["id"],
                ondelete="RESTRICT",
            )

    _create_immutable_fact_guards()
    _create_price_overlap_guard()
    _create_snapshot_guard()


def _drop_snapshot_columns(table_name: str) -> None:
    op.drop_index(f"ix_{table_name}_tenant_accepted_revision", table_name=table_name)
    for column, _target_table in (
        ("accepted_price_version_id", "price_versions"),
        ("accepted_routing_policy_id", "routing_policies"),
        ("accepted_model_deployment_id", "model_deployments"),
        ("accepted_model_revision_id", "model_revisions"),
    ):
        op.drop_constraint(f"fk_{table_name}_{column}", table_name, type_="foreignkey")
    op.drop_constraint(
        f"ck_{table_name}_accepted_snapshot_complete",
        table_name,
        type_="check",
    )
    for column in _SNAPSHOT_COLUMNS:
        op.drop_column(table_name, column)


def downgrade() -> None:
    for table_name in ("inference_requests", "generation_jobs"):
        op.execute(
            sa.text(f"DROP TRIGGER IF EXISTS trg_{table_name}_accepted_snapshot_immutable ON {table_name}")
        )
    op.execute(sa.text("DROP FUNCTION IF EXISTS reject_accepted_snapshot_mutation()"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_price_bindings_no_overlap ON price_bindings"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS reject_overlapping_price_binding()"))

    for table_name in ("generation_jobs", "inference_requests"):
        _drop_snapshot_columns(table_name)

    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_price_bindings_immutable ON price_bindings"
        )
    )
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_price_versions_immutable ON price_versions"
        )
    )
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_routing_policies_immutable ON routing_policies"
        )
    )
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS trg_model_revisions_immutable ON model_revisions"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS reject_versioned_catalog_fact_mutation()"))

    op.drop_index(
        "ix_price_bindings_revision_deployment_effective",
        table_name="price_bindings",
    )
    op.drop_table("price_bindings")
    op.drop_index("ix_price_versions_revision_effective", table_name="price_versions")
    op.drop_table("price_versions")
    op.drop_index("ix_routing_policies_revision_version", table_name="routing_policies")
    op.drop_table("routing_policies")
    op.drop_index("ix_model_revisions_product_model_version", table_name="model_revisions")
    op.drop_table("model_revisions")
