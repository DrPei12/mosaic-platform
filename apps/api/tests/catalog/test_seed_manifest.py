from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.catalog import live_evidence
from app.catalog.manifest import (
    DEPLOYMENTS,
    ENDPOINTS,
    MODEL_REVISIONS,
    PRICE_VERSIONS,
    PRODUCTS,
    REQUIRED_LIVE_MODALITIES,
    ROUTING_POLICIES,
    capability_schema_hash,
    manifest_digest,
)
from app.infrastructure.models import ModelDeployments, ProductModels, ProviderEndpoints
from scripts import seed_product_catalog as seed_module
from scripts.seed_product_catalog import (
    BASE_LIVE_PRODUCT_KEYS,
    EXPECTED_LIVE_MODELS,
    LIVE_EVIDENCE_SMOKE_SCRIPT_PATH,
    _evidence_passes,
    deterministic_fact_id,
    validate_activation_evidence,
)


def test_manifest_is_secret_free_and_has_all_required_modalities() -> None:
    assert {item["secret_ref"] for item in ENDPOINTS} == {"env:DASHSCOPE_API_KEY"}
    assert {item["model_key"] for item in PRODUCTS} >= {
        "qwen-3-5-plus",
        "qwen-image-3-0-pro",
        "wan-2-7",
        "qwen3-tts-base",
        "qwen3-tts-flash",
        "qwen3-tts-voice-design",
        "qwen3-tts-custom-voice",
    }
    assert {item["status"] for item in ENDPOINTS} == {"degraded"}
    assert {item["protocol"] for item in ENDPOINTS} == {
        "openai_compatible",
        "dashscope_http",
    }
    assert {item["status"] for item in DEPLOYMENTS} == {"disabled"}
    assert BASE_LIVE_PRODUCT_KEYS == {
        "qwen-3-5-plus",
        "qwen-image-3-0-pro",
        "wan-2-7",
        "qwen3-tts-flash",
    }
    assert "qwen3-tts-base" not in {item["model_key"] for item in DEPLOYMENTS}
    base = next(item for item in PRODUCTS if item["model_key"] == "qwen3-tts-base")
    assert base["capabilities"]["execution_policy"] == "unsupported"
    audio_routes = {
        item["model_key"]: item for item in DEPLOYMENTS if item["model_key"].startswith("qwen3-tts")
    }
    assert audio_routes["qwen3-tts-flash"]["routing_config"]["default_voice"] == "Cherry"
    assert audio_routes["qwen3-tts-voice-design"]["provider_model_id"] == "qwen3-tts-vd-2026-01-26"
    assert audio_routes["qwen3-tts-custom-voice"]["provider_model_id"] == "qwen3-tts-vc-2026-01-22"
    assert REQUIRED_LIVE_MODALITIES == {"text", "image", "video", "audio"}


def test_activation_requires_all_real_live_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    hmac_key = "unit-test-live-evidence-key-123456"
    monkeypatch.setenv(live_evidence.LIVE_EVIDENCE_HMAC_KEY_ENV, hmac_key)
    source_facts: dict[str, Any] = {
        "source_commit": "a" * 40,
        "catalog_manifest_digest": manifest_digest(),
        "smoke_script_sha256": "b" * 64,
        "source_tree_clean": True,
    }
    monkeypatch.setattr(
        live_evidence,
        "current_live_evidence_facts",
        lambda _smoke_script_path: dict(source_facts),
    )

    unsigned_evidence: dict[str, Any] = {
        "live": True,
        "status": "ok",
        "run_id": str(uuid4()),
        "started_at": datetime.now(UTC).isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "checks": [
            {
                "modality": modality,
                "status": "ok",
                "model_requested": EXPECTED_LIVE_MODELS[modality],
                "model_reported": (
                    EXPECTED_LIVE_MODELS[modality] if modality == "text" else None
                ),
                "request_id_present": True,
                "usage_present": True,
                **(
                    {"output_chars": 1}
                    if modality == "text"
                    else {"artifacts": 1, "artifact_bytes": 1}
                ),
            }
            for modality in REQUIRED_LIVE_MODALITIES
        ],
    }
    evidence = live_evidence.bind_live_evidence(
        unsigned_evidence,
        smoke_script_path=LIVE_EVIDENCE_SMOKE_SCRIPT_PATH,
        key=hmac_key,
    )

    def resign(value: dict[str, Any]) -> dict[str, Any]:
        return live_evidence.bind_live_evidence(
            value,
            smoke_script_path=LIVE_EVIDENCE_SMOKE_SCRIPT_PATH,
            key=hmac_key,
        )

    assert _evidence_passes(evidence)
    validate_activation_evidence(evidence)

    duplicate = {
        **evidence,
        "checks": [*evidence["checks"], dict(evidence["checks"][0])],
    }
    with pytest.raises(ValueError):
        validate_activation_evidence(resign(duplicate))

    stale = resign(
        {
            **evidence,
            "completed_at": (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
        }
    )
    with pytest.raises(ValueError):
        validate_activation_evidence(stale)

    checks = evidence["checks"]
    assert isinstance(checks, list)
    incomplete = resign({**evidence, "checks": checks[:-1]})
    assert not _evidence_passes(incomplete)

    missing_usage = resign(
        {
            **evidence,
            "checks": [
                {**check, "usage_present": False}
                if check["modality"] == "text"
                else check
                for check in checks
            ],
        }
    )
    assert not _evidence_passes(missing_usage)

    empty_output = resign(
        {
            **evidence,
            "checks": [
                {
                    **check,
                    **(
                        {"output_chars": 0}
                        if check["modality"] == "text"
                        else {"artifact_bytes": 0}
                    ),
                }
                for check in checks
            ],
        }
    )
    assert not _evidence_passes(empty_output)

    wrong_model = resign(
        {
            **evidence,
            "checks": [
                {**check, "model_requested": "qwen3-tts-1-7b-base"}
                if check["modality"] == "audio"
                else check
                for check in checks
            ],
        }
    )
    assert not _evidence_passes(wrong_model)


def test_upsert_targets_compile_for_postgresql_only() -> None:
    product_statement = (
        select(ProductModels.id)
        .where(ProductModels.model_key == "qwen-3-5-plus")
        .with_for_update()
    )
    endpoint_statement = select(ProviderEndpoints.id).where(
        ProviderEndpoints.endpoint_key == "bailian-openai-compatible"
    )
    deployment_statement = select(ModelDeployments.id).where(
        ModelDeployments.provider_model_id == "qwen3.5-plus"
    )
    for statement in (product_statement, endpoint_statement, deployment_statement):
        compiled = statement.compile(dialect=postgresql.dialect())  # type: ignore[no-untyped-call]
        assert "SELECT" in str(compiled)


@pytest.mark.asyncio
async def test_normal_seed_forces_existing_routes_back_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingSession:
        def __init__(self) -> None:
            self.statements: list[object] = []

        async def execute(self, statement: object) -> None:
            self.statements.append(statement)

    session = RecordingSession()
    endpoint_ids = {str(item["endpoint_key"]): uuid4() for item in ENDPOINTS}
    product_ids = {str(item["model_key"]): uuid4() for item in PRODUCTS}

    async def fake_lookup(_session: object) -> tuple[dict[str, UUID], dict[str, UUID]]:
        return endpoint_ids, product_ids

    monkeypatch.setattr(seed_module, "_lookup_ids", fake_lookup)

    await seed_module._upsert_endpoints(session)  # type: ignore[arg-type]
    await seed_module._upsert_deployments(session)  # type: ignore[arg-type]

    conflict_sql = [
        str(statement.compile(dialect=postgresql.dialect())).lower()
        for statement in session.statements
        if "on conflict" in str(statement.compile(dialect=postgresql.dialect())).lower()
    ]
    assert len(conflict_sql) == len(ENDPOINTS) + len(DEPLOYMENTS)
    assert all("status =" in sql for sql in conflict_sql)


def test_versioned_manifest_is_deterministic_and_priority_only() -> None:
    assert manifest_digest() == (
        "7261731150de2a8f4eef0beaa0138202c11b20107b4536adfaec43a2044b07d9"
    )
    assert len(MODEL_REVISIONS) == len(PRODUCTS)
    assert len(ROUTING_POLICIES) == len(PRODUCTS)
    assert len(PRICE_VERSIONS) == len(PRODUCTS)
    assert {item["strategy"] for item in ROUTING_POLICIES} == {"priority"}
    for price in PRICE_VERSIONS:
        tariff = price["pricing"]
        assert tariff["schema"] == "local_tariff_v1"
        assert price["currency"] == "PTS"
        assert tariff["currency"] == "PTS"
        assert tariff["rounding"] == "integer_sum"
        assert tariff["reservation_minor"] > 0
        assert tariff["minimum_charge_minor"] > 0
        assert all(rate > 0 for rate in tariff["components"].values())
    for revision in MODEL_REVISIONS:
        schema = revision["capability_schema"]
        assert isinstance(schema, dict)
        assert revision["capability_schema_hash"] == capability_schema_hash(schema)
        assert deterministic_fact_id(
            "model-revision",
            str(revision["model_key"]),
            int(revision["version"]),
        ) == deterministic_fact_id(
            "model-revision",
            str(revision["model_key"]),
            int(revision["version"]),
        )
    assert deterministic_fact_id("model-revision", "qwen-3-5-plus", 1) == UUID(
        "26112c06-5655-5ac6-b61b-4430d827141c"
    )


def test_versioned_manifest_price_windows_are_valid() -> None:
    for price in PRICE_VERSIONS:
        assert price["effective_from"] < "9999-01-01T00:00:00+00:00"
        assert price["effective_to"] is None or price["effective_to"] > price["effective_from"]
