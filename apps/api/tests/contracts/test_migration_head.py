from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_production_schema_revision_is_the_single_migration_head() -> None:
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260826_0013"]


def test_versioned_catalog_migration_has_immutable_and_overlap_guards() -> None:
    root = Path(__file__).parents[2]
    source = (root / "migrations" / "versions" / "20260826_0008_versioned_catalog_facts.py").read_text(
        encoding="utf-8"
    )
    assert "reject_versioned_catalog_fact_mutation" in source
    assert "reject_accepted_snapshot_mutation" in source
    assert "reject_overlapping_price_binding" in source
    assert "pg_advisory_xact_lock" in source


def test_identity_lifecycle_migration_adds_invite_credential_state_and_downgrades_to_0009() -> None:
    root = Path(__file__).parents[2]
    source = (
        root / "migrations" / "versions" / "20260826_0010_identity_lifecycle.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "20260826_0010"' in source
    assert 'down_revision: str | None = "20260826_0009"' in source
    for column in ("password_change_required", "credential_expires_at", "credential_used_at"):
        assert f'"{column}"' in source
    assert "ck_users_credential_lifecycle" in source
