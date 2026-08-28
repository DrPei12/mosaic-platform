from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app.api.models import get_catalog_service, router
from app.auth.dependencies import current_auth
from app.catalog.repository import CatalogRecord, DeploymentSnapshot
from app.catalog.service import ModelCatalogService

TENANT_ID = UUID("00000000-0000-0000-0000-000000000099")


class FakeCatalogRepository:
    def __init__(self) -> None:
        self.tenant_id: UUID | None = None

    async def list_for_tenant(self, tenant_id: UUID) -> tuple[CatalogRecord, ...]:
        self.tenant_id = tenant_id
        return (
            CatalogRecord(
                product_model_id=UUID("00000000-0000-0000-0000-000000000098"),
                model_key="qwen-3-5-plus",
                display_name="Qwen 3.5 Plus",
                modality="text",
                task_type="chat",
                product_status="active",
                capabilities={"public_capabilities": ["多轮对话"], "collections": ["featured"]},
                pricing_summary={"zh-CN": "按量计费"},
                description="文本模型",
                deployments=(DeploymentSnapshot("active", "active"),),
            ),
        )


@pytest.mark.asyncio
async def test_models_route_uses_auth_tenant_and_public_projection() -> None:
    repository = FakeCatalogRepository()
    service = ModelCatalogService(repository)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_auth] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=UUID(int=100), role="member"),
    )
    app.dependency_overrides[get_catalog_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/models")

    assert response.status_code == 200
    assert repository.tenant_id == TENANT_ID
    body = response.json()
    assert body["items"][0]["model"]["product_model_id"] == "qwen-3-5-plus"
    assert "provider_model_id" not in body["items"][0]["model"]
