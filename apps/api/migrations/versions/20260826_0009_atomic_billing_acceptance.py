"""Link accepted requests and jobs to their transaction-local wallet holds."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0009"
down_revision: str | None = "20260826_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_reservation_link(table_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column("billing_reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        f"ix_{table_name}_tenant_billing_reservation",
        table_name,
        ["tenant_id", "billing_reservation_id"],
    )
    op.create_foreign_key(
        f"fk_{table_name}_billing_reservation_tenant",
        table_name,
        "balance_reservations",
        ["tenant_id", "billing_reservation_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    # 0008 shipped a provider-metered placeholder binding with an open-ended
    # window.  Retire only that binding window so the immutable v1 PriceVersion
    # remains historical and the v2 local tariff can be seeded at cutover.
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_price_bindings_immutable ON price_bindings"))
    op.execute(
        sa.text(
            "UPDATE price_bindings AS bindings "
            "SET effective_to = '2026-08-26T00:00:00+00:00'::timestamptz "
            "FROM price_versions AS prices "
            "WHERE bindings.price_version_id = prices.id "
            "AND bindings.effective_to IS NULL "
            "AND bindings.effective_from < '2026-08-26T00:00:00+00:00'::timestamptz "
            "AND prices.pricing->>'mode' = 'provider_metered'"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_price_bindings_immutable "
            "BEFORE UPDATE OR DELETE ON price_bindings "
            "FOR EACH ROW EXECUTE FUNCTION reject_versioned_catalog_fact_mutation()"
        )
    )
    # Nullable keeps historical pre-E3 rows readable.  New acceptance code
    # fills this link before the surrounding transaction can commit.
    _add_reservation_link("inference_requests")
    _add_reservation_link("generation_jobs")


def _drop_reservation_link(table_name: str) -> None:
    op.drop_constraint(
        f"fk_{table_name}_billing_reservation_tenant",
        table_name,
        type_="foreignkey",
    )
    op.drop_index(
        f"ix_{table_name}_tenant_billing_reservation",
        table_name=table_name,
    )
    op.drop_column(table_name, "billing_reservation_id")


def downgrade() -> None:
    _drop_reservation_link("generation_jobs")
    _drop_reservation_link("inference_requests")
