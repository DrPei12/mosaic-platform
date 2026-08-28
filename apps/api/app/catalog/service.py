"""Application service for tenant-scoped public model catalogs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.catalog.repository import CatalogRecord, CatalogRepository
from app.contracts.catalog import (
    CatalogCollection,
    ModelAvailability,
    ModelCategory,
    PublicModelCatalogItem,
    PublicModelCatalogResponse,
    PublicProductModel,
)
from app.core.settings import settings
from app.generations.voice_resources import (
    VoiceResourceUnavailable,
    resolve_audio_voice_binding,
)

_COLLECTIONS = frozenset({"featured", "popular", "new"})
_FALLBACK_CAPABILITIES = ["按模型说明使用"]
_FALLBACK_PRICING = "按实际用量计费"


def _public_capabilities(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return list(_FALLBACK_CAPABILITIES)
    raw = value.get("public_capabilities")
    if not isinstance(raw, list):
        return list(_FALLBACK_CAPABILITIES)
    result = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    return list(dict.fromkeys(result))[:32] or list(_FALLBACK_CAPABILITIES)


def _public_collections(value: Any) -> list[CatalogCollection]:
    if not isinstance(value, dict):
        return []
    raw = value.get("collections")
    if not isinstance(raw, list):
        return []
    return [item for item in dict.fromkeys(raw) if item in _COLLECTIONS]


def _public_input_schema(value: Any) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("input_schema")
    if not isinstance(raw, dict):
        return None
    # Input schemas are controlled product metadata.  Only JSON object values
    # are allowed; deployment/provider keys are never copied into this object.
    return {
        str(key): child
        for key, child in raw.items()
        if isinstance(key, str) and isinstance(child, dict)
    } or None


def _pricing_summary(value: Any) -> str:
    if isinstance(value, dict):
        for locale in ("zh-CN", "zh_cn", "en-US", "en_us"):
            selected = value.get(locale)
            if isinstance(selected, str) and selected.strip():
                return selected.strip()[:240]
        for selected in value.values():
            if isinstance(selected, str) and selected.strip():
                return selected.strip()[:240]
    return _FALLBACK_PRICING


def _has_voice_resource(record: CatalogRecord) -> bool:
    requires_resource = bool(record.capabilities.get("voice_resource_required"))
    if not requires_resource:
        return True
    for deployment in record.deployments:
        if deployment.status != "active" or deployment.endpoint_status != "active":
            continue
        try:
            binding = resolve_audio_voice_binding(
                provider_model_id=deployment.provider_model_id,
                routing_config=deployment.routing_config,
                entitlement_config=record.entitlement_config,
            )
        except VoiceResourceUnavailable:
            continue
        if binding is not None:
            return True
    return False


def calculate_availability(
    record: CatalogRecord,
    *,
    execution_enabled: bool = True,
) -> ModelAvailability:
    """Map internal route health to the deliberately coarse public state."""

    if (
        record.product_status != "active"
        or record.capabilities.get("execution_policy") == "unsupported"
        or not _has_voice_resource(record)
    ):
        return "unavailable"
    if not execution_enabled:
        return "maintenance"
    if any(
        deployment.status == "active" and deployment.endpoint_status == "active"
        for deployment in record.deployments
    ):
        return "available"
    if any(
        deployment.status in {"active", "draining"}
        and deployment.endpoint_status in {"degraded", "active"}
        for deployment in record.deployments
    ):
        return "maintenance"
    return "unavailable"


def to_public_item(
    record: CatalogRecord,
    *,
    execution_enabled: bool = True,
) -> PublicModelCatalogItem:
    """Project one internal record without provider/deployment leakage."""

    capabilities = _public_capabilities(record.capabilities)
    product = PublicProductModel(
        product_model_id=record.model_key,
        display_name=record.display_name,
        category=record.modality,  # type: ignore[arg-type]
        task_type=record.task_type,  # type: ignore[arg-type]
        description=(record.description or "按模型说明使用")[:1000],
        capabilities=capabilities,
        input_schema=_public_input_schema(record.capabilities),
        availability=calculate_availability(record, execution_enabled=execution_enabled),
        pricing_summary=_pricing_summary(record.pricing_summary),
    )
    return PublicModelCatalogItem(
        model=product,
        collections=_public_collections(record.capabilities),
    )


class ModelCatalogService:
    def __init__(
        self,
        repository: CatalogRepository,
        *,
        execution_enabled: bool | None = None,
    ) -> None:
        self.repository = repository
        self.execution_enabled = execution_enabled

    async def list_models(
        self,
        tenant_id: UUID,
        *,
        category: ModelCategory | None = None,
        search: str | None = None,
        collection: CatalogCollection | None = None,
    ) -> PublicModelCatalogResponse:
        normalized_search = search.strip().casefold() if search else ""
        items: list[PublicModelCatalogItem] = []
        for record in await self.repository.list_for_tenant(tenant_id):
            # Unsupported catalog placeholders are retained internally for
            # model identity and historical foreign keys, but are not shown in
            # a customer-facing catalog that promises every visible model is
            # executable.
            if record.capabilities.get("execution_policy") == "unsupported":
                continue
            execution_enabled = self.execution_enabled
            if execution_enabled is None:
                execution_enabled = (
                    settings.chat_submission_enabled
                    if record.modality == "text"
                    else settings.generation_submission_enabled
                )
            item = to_public_item(
                record,
                execution_enabled=execution_enabled,
            )
            model = item.model
            if category is not None and model.category != category:
                continue
            if collection is not None and collection not in item.collections:
                continue
            searchable = " ".join(
                [model.product_model_id, model.display_name, model.description, *model.capabilities]
            ).casefold()
            if normalized_search and normalized_search not in searchable:
                continue
            items.append(item)
        items.sort(key=lambda item: (item.model.display_name.casefold(), item.model.product_model_id))
        return PublicModelCatalogResponse(items=items)


__all__ = [
    "ModelCatalogService",
    "calculate_availability",
    "to_public_item",
]
