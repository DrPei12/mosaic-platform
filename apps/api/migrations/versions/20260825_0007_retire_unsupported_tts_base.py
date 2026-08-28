"""Retire unsupported Qwen3-TTS Base provider routes."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260825_0007"
down_revision: str | None = "20260824_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Preserve deployment rows for historical generation foreign keys while
    # ensuring no stale provider mapping can advertise or execute Base as a
    # different hosted model.
    op.execute(
        """
        UPDATE model_deployments
        SET status = 'disabled', updated_at = CURRENT_TIMESTAMP
        WHERE product_model_id IN (
            SELECT id FROM product_models WHERE model_key = 'qwen3-tts-base'
        )
        """
    )
    op.execute(
        """
        UPDATE product_models
        SET capabilities = jsonb_set(
                COALESCE(capabilities, '{}'::jsonb),
                '{execution_policy}',
                '"unsupported"'::jsonb,
                true
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE model_key = 'qwen3-tts-base'
        """
    )


def downgrade() -> None:
    # Removing the metadata marker is reversible.  Historical routes remain
    # disabled because a downgrade cannot safely infer which mapping, if any,
    # had been operator-approved before this migration.
    op.execute(
        """
        UPDATE product_models
        SET capabilities = COALESCE(capabilities, '{}'::jsonb) - 'execution_policy',
            updated_at = CURRENT_TIMESTAMP
        WHERE model_key = 'qwen3-tts-base'
        """
    )
