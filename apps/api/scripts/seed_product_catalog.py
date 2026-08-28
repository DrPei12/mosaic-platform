"""Seed the canonical Bailian product catalog into PostgreSQL.

Normal execution is deliberately safe for a production rollout: endpoints are
seeded as ``degraded`` and deployments as ``disabled``.  ``--activate`` is a
separate, fail-closed operation and requires a fresh, HMAC-signed live smoke
evidence JSON whose source facts match the current clean Git tree.  It never
accepts a provider key or model ID from the command line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid5

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.billing.ports import PriceSnapshot
from app.billing.pricing import parse_local_tariff
from app.catalog.live_evidence import (
    LiveEvidenceError,
    verify_live_evidence_integrity,
)
from app.catalog.manifest import (
    DEPLOYMENTS,
    ENDPOINTS,
    MANIFEST,
    MODEL_REVISIONS,
    PRICE_VERSIONS,
    PRODUCTS,
    REQUIRED_LIVE_MODALITIES,
    ROUTING_POLICIES,
    canonical_json_bytes,
    capability_schema_hash,
)
from app.infrastructure.database import session_factory
from app.infrastructure.models import (
    ModelDeployments,
    ModelRevisions,
    PriceBindings,
    PriceVersions,
    ProductModels,
    ProviderEndpoints,
    RoutingPolicies,
)

BASE_LIVE_PRODUCT_KEYS = frozenset(
    {"qwen-3-5-plus", "qwen-image-3-0-pro", "wan-2-7", "qwen3-tts-flash"}
)
EXPECTED_LIVE_MODELS = {
    "text": "qwen3.5-plus",
    "image": "qwen-image-3.0-pro",
    "video": "wan2.7-t2v",
    "audio": "qwen3-tts-flash",
}
LIVE_ENDPOINT_KEYS = ("bailian-openai-compatible", "bailian-dashscope-native")
FACT_NAMESPACE = UUID("4de3f58b-d6ab-5f6e-b3c6-934d1a7c1c52")
LIVE_EVIDENCE_SMOKE_SCRIPT_PATH = Path(__file__).resolve().with_name("provider_smoke.py")


def deterministic_fact_id(kind: str, key: str, version: int) -> UUID:
    """Derive stable IDs for immutable catalog facts from manifest identity."""

    return uuid5(FACT_NAMESPACE, f"{kind}:{key}:v{version}")


def _effective_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("price effective_from must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("price effective_from must include a timezone")
    return parsed.astimezone(UTC)


def _manifest_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"manifest {field} must be an integer")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed the MOSAIC product catalog")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="activate the four base routes only after a complete live-evidence file",
    )
    parser.add_argument(
        "--live-evidence-file",
        type=Path,
        help="HMAC-signed JSON emitted by provider_smoke.py --live; required with --activate",
    )
    return parser


def _evidence_passes(evidence: Mapping[str, Any]) -> bool:
    if not isinstance(evidence, Mapping):
        return False
    if evidence.get("live") is not True or evidence.get("status") != "ok":
        return False
    try:
        verify_live_evidence_integrity(
            evidence,
            smoke_script_path=LIVE_EVIDENCE_SMOKE_SCRIPT_PATH,
        )
    except LiveEvidenceError:
        return False
    try:
        UUID(str(evidence.get("run_id")))
        completed_at = datetime.fromisoformat(str(evidence.get("completed_at")))
    except (TypeError, ValueError):
        return False
    if completed_at.tzinfo is None:
        return False
    age = datetime.now(UTC) - completed_at.astimezone(UTC)
    if age < timedelta(minutes=-5) or age > timedelta(hours=24):
        return False
    checks = evidence.get("checks")
    if not isinstance(checks, list):
        return False
    by_modality = {
        item.get("modality"): item
        for item in checks
        if isinstance(item, Mapping) and isinstance(item.get("modality"), str)
    }
    if len(by_modality) != len(checks) or set(by_modality) != REQUIRED_LIVE_MODALITIES:
        return False
    for modality in REQUIRED_LIVE_MODALITIES:
        item = by_modality.get(modality)
        if not isinstance(item, Mapping):
            return False
        if (
            item.get("status") != "ok"
            or item.get("model_requested") != EXPECTED_LIVE_MODELS[modality]
        ):
            return False
        reported = item.get("model_reported")
        if modality == "text" and reported != EXPECTED_LIVE_MODELS[modality]:
            return False
        if modality != "text" and reported is not None:
            return False
        if item.get("request_id_present") is not True or item.get("usage_present") is not True:
            return False
        if modality == "text":
            output_chars = item.get("output_chars")
            if isinstance(output_chars, bool) or not isinstance(output_chars, int) or output_chars <= 0:
                return False
        else:
            artifacts = item.get("artifacts")
            artifact_bytes = item.get("artifact_bytes")
            if (
                isinstance(artifacts, bool)
                or not isinstance(artifacts, int)
                or artifacts <= 0
                or isinstance(artifact_bytes, bool)
                or not isinstance(artifact_bytes, int)
                or artifact_bytes <= 0
            ):
                return False
    return True


def validate_activation_evidence(evidence: Mapping[str, Any]) -> None:
    if not _evidence_passes(evidence):
        raise ValueError(
            "activation requires live=true, status=ok, expected requested/reported model IDs, "
            "request_id_present, usage_present, non-empty text/media output, fresh evidence, "
            "current source facts, and a valid HMAC"
        )


async def _upsert_endpoints(session: AsyncSession) -> None:
    for endpoint in ENDPOINTS:
        values = dict(endpoint)
        # The conflict update intentionally omits secret_ref.  An operator may
        # have rotated an existing secret reference; a seed must not overwrite
        # it with a literal credential or even silently replace the reference.
        update_values = {
            key: values[key]
            for key in (
                "provider_name",
                "protocol",
                "base_url",
                "timeout_ms",
                "status",
                "config",
            )
        }
        await session.execute(
            insert(ProviderEndpoints)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[ProviderEndpoints.endpoint_key],
                set_=update_values,
            )
        )


async def _upsert_products(session: AsyncSession) -> None:
    for product in PRODUCTS:
        await session.execute(
            insert(ProductModels)
            .values(**product)
            .on_conflict_do_update(
                index_elements=[ProductModels.model_key],
                set_={
                    key: product[key]
                    for key in (
                        "display_name",
                        "modality",
                        "task_type",
                        "status",
                        "capabilities",
                        "pricing_summary",
                        "description",
                    )
                },
            )
        )


async def _upsert_model_revisions(session: AsyncSession) -> None:
    product_rows = await session.execute(select(ProductModels.id, ProductModels.model_key))
    product_ids = {row.model_key: row.id for row in product_rows}
    for revision in MODEL_REVISIONS:
        model_key = str(revision["model_key"])
        product_id = product_ids.get(model_key)
        schema = revision.get("capability_schema")
        schema_hash = revision.get("capability_schema_hash")
        version = _manifest_int(revision["version"], "model revision version")
        if product_id is None:
            raise RuntimeError(f"manifest references unknown product model: {model_key}")
        if not isinstance(schema, Mapping) or not isinstance(schema_hash, str):
            raise TypeError(f"invalid capability schema for {model_key}")
        if capability_schema_hash(schema) != schema_hash:
            raise RuntimeError(f"capability schema hash mismatch for {model_key}")
        values = {
            "id": deterministic_fact_id("model-revision", model_key, version),
            "product_model_id": product_id,
            "model_key": model_key,
            "modality": next(
                str(product["modality"])
                for product in PRODUCTS
                if str(product["model_key"]) == model_key
            ),
            "task_type": next(
                str(product["task_type"])
                for product in PRODUCTS
                if str(product["model_key"]) == model_key
            ),
            "version": version,
            "capability_schema_version": _manifest_int(
                revision["capability_schema_version"],
                "capability schema version",
            ),
            "capability_schema": dict(schema),
            "capability_schema_hash": schema_hash,
        }
        await session.execute(
            insert(ModelRevisions)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[ModelRevisions.product_model_id, ModelRevisions.version]
            )
        )
        existing = await session.execute(
            select(ModelRevisions).where(
                ModelRevisions.product_model_id == product_id,
                ModelRevisions.version == version,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None or row.capability_schema_hash != schema_hash:
            raise RuntimeError(f"immutable model revision mismatch for {model_key} v{version}")
        if canonical_json_bytes(row.capability_schema) != canonical_json_bytes(dict(schema)):
            raise RuntimeError(f"immutable model revision schema mismatch for {model_key} v{version}")


async def _revision_ids(session: AsyncSession) -> dict[str, UUID]:
    rows = await session.execute(
        select(ProductModels.model_key, ModelRevisions.id)
        .join(ModelRevisions, ModelRevisions.product_model_id == ProductModels.id)
        .where(ModelRevisions.version == 1)
    )
    return {row.model_key: row.id for row in rows}


async def _upsert_routing_policies(session: AsyncSession) -> None:
    revision_ids = await _revision_ids(session)
    for policy in ROUTING_POLICIES:
        model_key = str(policy["model_key"])
        revision_id = revision_ids.get(model_key)
        version = _manifest_int(policy["version"], "routing policy version")
        config = policy.get("config")
        if revision_id is None:
            raise RuntimeError(f"manifest references unknown model revision: {model_key}")
        if not isinstance(config, Mapping):
            raise TypeError(f"invalid routing policy config for {model_key}")
        values = {
            "id": deterministic_fact_id("routing-policy", model_key, version),
            "model_revision_id": revision_id,
            "policy_key": str(policy["policy_key"]),
            "version": version,
            "strategy": str(policy["strategy"]),
            "config": dict(config),
        }
        await session.execute(
            insert(RoutingPolicies)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[RoutingPolicies.model_revision_id, RoutingPolicies.version]
            )
        )
        existing = await session.execute(
            select(RoutingPolicies).where(
                RoutingPolicies.model_revision_id == revision_id,
                RoutingPolicies.version == version,
            )
        )
        row = existing.scalar_one_or_none()
        if (
            row is None
            or row.policy_key != values["policy_key"]
            or row.strategy != values["strategy"]
            or canonical_json_bytes(row.config) != canonical_json_bytes(dict(config))
        ):
            raise RuntimeError(f"immutable routing policy mismatch for {model_key} v{version}")


async def _upsert_price_versions(session: AsyncSession) -> None:
    revision_ids = await _revision_ids(session)
    for price in PRICE_VERSIONS:
        model_key = str(price["model_key"])
        revision_id = revision_ids.get(model_key)
        version = _manifest_int(price["version"], "price version")
        pricing = price.get("pricing")
        if revision_id is None:
            raise RuntimeError(f"manifest references unknown model revision: {model_key}")
        if not isinstance(pricing, Mapping):
            raise TypeError(f"invalid pricing for {model_key}")
        values = {
            "id": deterministic_fact_id("price-version", model_key, version),
            "model_revision_id": revision_id,
            "price_key": str(price["price_key"]),
            "version": version,
            "currency": str(price["currency"]),
            "unit": str(price["unit"]),
            "pricing": dict(pricing),
            "effective_from": _effective_at(price["effective_from"]),
            "effective_to": (
                _effective_at(price["effective_to"])
                if price.get("effective_to") is not None
                else None
            ),
        }
        # Fail the seed before any catalog write can commit if a release
        # accidentally publishes an ambiguous or zero-priced tariff.
        parse_local_tariff(
            PriceSnapshot(
                price_version_id=cast(UUID, values["id"]),
                price_key=cast(str, values["price_key"]),
                version=version,
                currency=cast(str, values["currency"]),
                unit=cast(str, values["unit"]),
                pricing=cast(Mapping[str, object], values["pricing"]),
            )
        )
        await session.execute(
            insert(PriceVersions)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[PriceVersions.model_revision_id, PriceVersions.version]
            )
        )
        existing = await session.execute(
            select(PriceVersions).where(
                PriceVersions.model_revision_id == revision_id,
                PriceVersions.version == version,
            )
        )
        row = existing.scalar_one_or_none()
        if (
            row is None
            or row.price_key != values["price_key"]
            or row.currency != values["currency"]
            or row.unit != values["unit"]
            or canonical_json_bytes(row.pricing) != canonical_json_bytes(dict(pricing))
            or row.effective_from != values["effective_from"]
            or row.effective_to != values["effective_to"]
        ):
            raise RuntimeError(f"immutable price version mismatch for {model_key} v{version}")


async def _lookup_ids(session: AsyncSession) -> tuple[dict[str, Any], dict[str, Any]]:
    endpoint_rows = await session.execute(select(ProviderEndpoints.id, ProviderEndpoints.endpoint_key))
    endpoint_ids = {row.endpoint_key: row.id for row in endpoint_rows}
    product_rows = await session.execute(select(ProductModels.id, ProductModels.model_key))
    product_ids = {row.model_key: row.id for row in product_rows}
    return endpoint_ids, product_ids


async def _upsert_deployments(session: AsyncSession) -> None:
    endpoint_ids, product_ids = await _lookup_ids(session)
    # Base has no Bailian hosted execution route.  Preserve historical rows for
    # generation foreign keys, but retire every route so stale operator data
    # cannot make the product appear callable as another model.
    base_product_id = product_ids.get("qwen3-tts-base")
    if base_product_id is not None:
        await session.execute(
            update(ModelDeployments)
            .where(ModelDeployments.product_model_id == base_product_id)
            .values(status="disabled")
        )
    for deployment in DEPLOYMENTS:
        model_key = str(deployment["model_key"])
        endpoint_key = str(deployment["endpoint_key"])
        try:
            values = {
                **deployment,
                "product_model_id": product_ids[model_key],
                "provider_endpoint_id": endpoint_ids[endpoint_key],
            }
        except KeyError as error:
            raise RuntimeError(f"manifest references unknown catalog key: {error}") from error
        values.pop("model_key", None)
        values.pop("endpoint_key", None)
        await session.execute(
            insert(ModelDeployments)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[
                    ModelDeployments.product_model_id,
                    ModelDeployments.provider_endpoint_id,
                ],
                set_={
                    key: values[key]
                    for key in (
                        "provider_model_id",
                        "status",
                        "priority",
                        "concurrency_limit",
                        "routing_config",
                    )
                },
            )
        )


async def _upsert_price_bindings(session: AsyncSession) -> None:
    revision_ids = await _revision_ids(session)
    price_rows = await session.execute(
        select(ProductModels.model_key, PriceVersions.version, PriceVersions.id)
        .join(ModelRevisions, ModelRevisions.product_model_id == ProductModels.id)
        .join(PriceVersions, PriceVersions.model_revision_id == ModelRevisions.id)
        .where(ModelRevisions.version == 1)
    )
    price_ids = {(row.model_key, int(row.version)): row.id for row in price_rows}
    price_values = {str(item["model_key"]): item for item in PRICE_VERSIONS}

    deployment_rows = await session.execute(
        select(
            ModelDeployments.id,
            ProductModels.model_key,
            ProviderEndpoints.endpoint_key,
        )
        .join(ProductModels, ProductModels.id == ModelDeployments.product_model_id)
        .join(ProviderEndpoints, ProviderEndpoints.id == ModelDeployments.provider_endpoint_id)
    )
    deployment_ids = {(row.model_key, row.endpoint_key): row.id for row in deployment_rows}
    for deployment in DEPLOYMENTS:
        model_key = str(deployment["model_key"])
        endpoint_key = str(deployment["endpoint_key"])
        revision_id = revision_ids.get(model_key)
        price = price_values.get(model_key)
        deployment_id = deployment_ids.get((model_key, endpoint_key))
        version = _manifest_int(price["version"], "price version") if price is not None else 1
        price_id = price_ids.get((model_key, version))
        if revision_id is None or price_id is None or deployment_id is None or price is None:
            raise RuntimeError(
                f"manifest references incomplete price binding: {model_key}/{endpoint_key}"
            )
        values = {
            "id": deterministic_fact_id(
                "price-binding",
                f"{model_key}:{endpoint_key}",
                version,
            ),
            "model_revision_id": revision_id,
            "model_deployment_id": deployment_id,
            "price_version_id": price_id,
            "effective_from": _effective_at(price["effective_from"]),
            "effective_to": (
                _effective_at(price["effective_to"])
                if price.get("effective_to") is not None
                else None
            ),
        }
        await session.execute(
            insert(PriceBindings)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    PriceBindings.model_revision_id,
                    PriceBindings.model_deployment_id,
                    PriceBindings.price_version_id,
                ]
            )
        )


async def activate_base_routes(session: AsyncSession, evidence: Mapping[str, Any]) -> None:
    """Activate only routes covered by complete live evidence.

    VoiceDesign and CustomVoice intentionally stay disabled until the separate
    tenant voice-resource workflow exists.
    """

    validate_activation_evidence(evidence)
    await session.execute(
        update(ProviderEndpoints)
        .where(ProviderEndpoints.endpoint_key.in_(LIVE_ENDPOINT_KEYS))
        .values(status="active")
    )
    await session.execute(
        update(ModelDeployments)
        .where(
            ModelDeployments.product_model_id.in_(
                select(ProductModels.id).where(
                    ProductModels.model_key.in_(BASE_LIVE_PRODUCT_KEYS)
                )
            ),
            ModelDeployments.provider_model_id.in_(EXPECTED_LIVE_MODELS.values()),
        )
        .values(status="active")
    )


async def seed_catalog(
    session: AsyncSession, *, activate: bool = False, evidence: Mapping[str, Any] | None = None
) -> None:
    """Apply the canonical idempotent seed in one transaction."""

    if activate:
        if evidence is None:
            raise ValueError("--activate requires --live-evidence-file")
        validate_activation_evidence(evidence)
    await _upsert_endpoints(session)
    await _upsert_products(session)
    await _upsert_model_revisions(session)
    await _upsert_routing_policies(session)
    await _upsert_price_versions(session)
    await _upsert_deployments(session)
    await _upsert_price_bindings(session)
    if activate:
        assert evidence is not None
        await activate_base_routes(session, evidence)


async def _run(args: argparse.Namespace) -> None:
    evidence: Mapping[str, Any] | None = None
    if args.activate:
        if args.live_evidence_file is None:
            raise ValueError("--activate requires --live-evidence-file")
        evidence_payload = json.loads(args.live_evidence_file.read_text(encoding="utf-8"))
        if not isinstance(evidence_payload, Mapping):
            raise ValueError("live evidence JSON must be an object")
        evidence = evidence_payload
    async with session_factory() as session, session.begin():
        await seed_catalog(session, activate=args.activate, evidence=evidence)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        asyncio.run(_run(args))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"catalog seed failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "ok", "manifest": "canonical", "activated": args.activate}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASE_LIVE_PRODUCT_KEYS",
    "EXPECTED_LIVE_MODELS",
    "FACT_NAMESPACE",
    "LIVE_ENDPOINT_KEYS",
    "LIVE_EVIDENCE_SMOKE_SCRIPT_PATH",
    "MANIFEST",
    "activate_base_routes",
    "deterministic_fact_id",
    "seed_catalog",
    "validate_activation_evidence",
]
