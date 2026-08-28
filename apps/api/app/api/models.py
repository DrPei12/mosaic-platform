"""Tenant-scoped public model catalog routes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import require_permission
from app.auth.repository import CurrentAuth
from app.catalog.repository import SqlAlchemyCatalogRepository
from app.catalog.service import ModelCatalogService
from app.contracts.catalog import (
    CatalogCollection,
    ModelCategory,
    PublicModelCatalogResponse,
)
from app.infrastructure.database import get_db_session

router = APIRouter(prefix="/api/v1/models", tags=["models"])
require_catalog_permission = require_permission("catalog:read")


async def get_catalog_session(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AsyncIterator[AsyncSession]:
    yield session


def get_catalog_service(
    session: Annotated[AsyncSession, Depends(get_catalog_session)],
) -> ModelCatalogService:
    return ModelCatalogService(SqlAlchemyCatalogRepository(session))


@router.get("", response_model=PublicModelCatalogResponse)
async def list_models(
    auth: Annotated[CurrentAuth, Depends(require_catalog_permission)],
    service: Annotated[ModelCatalogService, Depends(get_catalog_service)],
    category: Annotated[ModelCategory | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    collection: Annotated[CatalogCollection | None, Query()] = None,
) -> PublicModelCatalogResponse:
    """List only products entitled to the authenticated tenant.

    ``tenant_id`` is taken exclusively from the auth context.  There is no
    tenant query parameter and the public projection contains no provider
    endpoint, deployment, secret or provider model ID.
    """

    return await service.list_models(
        auth.tenant_id,
        category=category,
        search=search,
        collection=collection,
    )


__all__ = ["get_catalog_service", "get_catalog_session", "list_models", "router"]
