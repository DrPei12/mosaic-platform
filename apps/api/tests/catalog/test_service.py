from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from app.catalog.repository import CatalogRecord, DeploymentSnapshot
from app.catalog.service import (
    ModelCatalogService,
    calculate_availability,
    to_public_item,
)

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def record(
    key: str,
    *,
    modality: str = "text",
    collections: list[str] | None = None,
    deployment: DeploymentSnapshot | None = None,
    voice_resource_required: bool = False,
    voice_resource: dict[str, object] | None = None,
    execution_policy: str | None = None,
) -> CatalogRecord:
    config: dict[str, object] = {}
    if voice_resource is not None:
        config["voice_resource"] = voice_resource
    capabilities: dict[str, object] = {
        "public_capabilities": ["真实调用", "流式输出"],
        "collections": collections or ["featured"],
    }
    if voice_resource_required:
        capabilities["voice_resource_required"] = True
    if execution_policy is not None:
        capabilities["execution_policy"] = execution_policy
    return CatalogRecord(
        product_model_id=uuid4(),
        model_key=key,
        display_name=key.replace("-", " ").title(),
        modality=modality,
        task_type="chat" if modality == "text" else "tts",
        product_status="active",
        capabilities=capabilities,
        pricing_summary={"zh-CN": "按实际用量计费"},
        description="生产产品",
        entitlement_config=config,
        deployments=(deployment,) if deployment is not None else (),
    )


class FakeCatalogRepository:
    def __init__(self, rows: Sequence[CatalogRecord]) -> None:
        self.rows = tuple(rows)
        self.requested_tenant: UUID | None = None

    async def list_for_tenant(self, tenant_id: UUID) -> Sequence[CatalogRecord]:
        self.requested_tenant = tenant_id
        return self.rows

    async def grant_default_entitlements(
        self, tenant_id: UUID, model_keys: Sequence[str] | None = None
    ) -> int:
        return 0


@pytest.mark.parametrize(
    ("deployment", "expected"),
    [
        (DeploymentSnapshot(status="active", endpoint_status="active"), "available"),
        (DeploymentSnapshot(status="active", endpoint_status="degraded"), "maintenance"),
        (DeploymentSnapshot(status="disabled", endpoint_status="active"), "unavailable"),
        (None, "unavailable"),
    ],
)
def test_availability_is_derived_from_internal_route_health(
    deployment: DeploymentSnapshot | None, expected: str
) -> None:
    assert calculate_availability(record("qwen-3-5-plus", deployment=deployment)) == expected


def test_voice_products_are_unavailable_without_tenant_voice_resource() -> None:
    row = record(
        "qwen3-tts-voice-design",
        modality="audio",
        voice_resource_required=True,
        voice_resource=None,
        deployment=DeploymentSnapshot(
            status="active",
            endpoint_status="active",
            provider_model_id="qwen3-tts-vd-2026-01-26",
            routing_config={"live_modality": "audio", "voice_resource_required": True},
        ),
    )
    assert calculate_availability(row) == "unavailable"

    row_with_resource = record(
        "qwen3-tts-voice-design",
        modality="audio",
        voice_resource_required=True,
        voice_resource={
            "status": "active",
            "target_model": "qwen3-tts-vd-2026-01-26",
            "provider_voice_id": "voice-resource-1",
        },
        deployment=DeploymentSnapshot(
            status="active",
            endpoint_status="active",
            provider_model_id="qwen3-tts-vd-2026-01-26",
            routing_config={"live_modality": "audio", "voice_resource_required": True},
        ),
    )
    assert calculate_availability(row_with_resource) == "available"

    mismatched = replace(
        row_with_resource,
        entitlement_config={
            "voice_resource": {
                "status": "active",
                "target_model": "qwen3-tts-vc-2026-01-22",
                "provider_voice_id": "voice-resource-1",
            }
        },
    )
    assert calculate_availability(mismatched) == "unavailable"


def test_unsupported_product_stays_unavailable_with_a_dirty_active_route() -> None:
    base = record(
        "qwen3-tts-base",
        modality="audio",
        execution_policy="unsupported",
        deployment=DeploymentSnapshot(status="active", endpoint_status="active"),
    )
    assert calculate_availability(base) == "unavailable"


def test_active_route_is_not_advertised_available_without_execution_stack() -> None:
    active = record(
        "qwen-3-5-plus",
        deployment=DeploymentSnapshot(status="active", endpoint_status="active"),
    )

    assert calculate_availability(active, execution_enabled=False) == "maintenance"


def test_public_projection_does_not_expose_provider_fields() -> None:
    item = to_public_item(
        record(
            "qwen-3-5-plus",
            deployment=DeploymentSnapshot(status="active", endpoint_status="active"),
        )
    )
    payload = item.model_dump(mode="json")
    assert payload["model"]["availability"] == "available"
    assert "provider_model_id" not in payload
    assert "provider_endpoint_id" not in payload
    assert "secret_ref" not in payload


@pytest.mark.asyncio
async def test_catalog_is_tenant_scoped_and_supports_filters() -> None:
    repository = FakeCatalogRepository(
        [
            record("qwen-3-5-plus", collections=["featured", "popular"]),
            record("qwen-image-3-0-pro", modality="image", collections=["popular"]),
        ]
    )
    service = ModelCatalogService(repository)

    response = await service.list_models(
        TENANT_ID,
        category="image",
        search="image",
        collection="popular",
    )

    assert repository.requested_tenant == TENANT_ID
    assert [item.model.product_model_id for item in response.items] == ["qwen-image-3-0-pro"]


@pytest.mark.asyncio
async def test_catalog_hides_unsupported_placeholders() -> None:
    repository = FakeCatalogRepository(
        [
            record(
                "qwen3-tts-base",
                modality="audio",
                execution_policy="unsupported",
                deployment=DeploymentSnapshot(status="active", endpoint_status="active"),
            ),
            record(
                "qwen3-tts-flash",
                modality="audio",
                deployment=DeploymentSnapshot(status="active", endpoint_status="active"),
            ),
        ]
    )

    response = await ModelCatalogService(repository).list_models(TENANT_ID)

    assert [item.model.product_model_id for item in response.items] == ["qwen3-tts-flash"]


@pytest.mark.asyncio
async def test_text_and_media_availability_use_separate_execution_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.catalog.service as service_module

    monkeypatch.setattr(service_module.settings, "chat_submission_enabled", True)
    monkeypatch.setattr(service_module.settings, "generation_submission_enabled", False)
    deployment = DeploymentSnapshot(status="active", endpoint_status="active")
    service = ModelCatalogService(
        FakeCatalogRepository(
            [
                record("qwen-3-5-plus", deployment=deployment),
                record("qwen-image-3-0-pro", modality="image", deployment=deployment),
            ]
        )
    )

    response = await service.list_models(TENANT_ID)
    availability = {
        item.model.product_model_id: item.model.availability for item in response.items
    }
    assert availability == {
        "qwen-3-5-plus": "available",
        "qwen-image-3-0-pro": "maintenance",
    }


@pytest.mark.asyncio
async def test_malformed_public_metadata_uses_safe_fallbacks() -> None:
    row = record("qwen-3-5-plus")
    row = replace(
        row,
        capabilities={"public_capabilities": [" ", "安全"]},
        pricing_summary={"zh-CN": " "},
    )
    item = to_public_item(row)
    assert item.model.capabilities == ["安全"]
    assert item.model.pricing_summary == "按实际用量计费"
