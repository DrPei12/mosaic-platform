from pathlib import Path


def test_rls_migration_covers_every_tenant_data_table() -> None:
    root = Path(__file__).parents[2]
    source = (
        root / "migrations" / "versions" / "20260826_0012_tenant_rls.py"
    ).read_text(encoding="utf-8")
    for table_name in (
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
    ):
        assert f'"{table_name}"' in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "mosaic_current_tenant_id" in source
    assert "WITH CHECK" in source
