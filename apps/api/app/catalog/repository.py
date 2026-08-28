"""Persistence ports and PostgreSQL implementation for the product catalog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.ports import PriceSnapshot
from app.infrastructure.database import session_factory
from app.infrastructure.models import (
    ModelDeployments,
    ModelRevisions,
    PriceBindings,
    PriceVersions,
    ProductModels,
    ProviderEndpoints,
    RoutingPolicies,
    TenantModelEntitlements,
)


@dataclass(frozen=True, slots=True)
class DeploymentSnapshot:
    """Provider deployment state needed to calculate public availability."""

    status: str
    endpoint_status: str
    provider_model_id: str = ""
    routing_config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    """Tenant-filtered product data with provider details kept internal."""

    product_model_id: UUID
    model_key: str
    display_name: str
    modality: str
    task_type: str
    product_status: str
    capabilities: Mapping[str, Any]
    pricing_summary: Mapping[str, Any]
    description: str | None
    entitlement_config: Mapping[str, Any] = field(default_factory=dict)
    deployments: tuple[DeploymentSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class AcceptedDecisionSnapshot:
    """The immutable catalog facts accepted alongside one worker record."""

    model_revision_id: UUID
    model_deployment_id: UUID
    routing_policy_id: UUID
    price_version_id: UUID
    price: PriceSnapshot
    capability_schema_version: int
    capability_schema_hash: str
    capability_schema: Mapping[str, Any]


def _accepted_decision_statement(
    *,
    product_model_id: UUID,
    model_deployment_id: UUID,
    effective_at: datetime,
) -> Select[Any]:
    return (
        select(ModelRevisions, RoutingPolicies, PriceVersions)
        .select_from(ModelRevisions)
        .join(
            ModelDeployments,
            and_(
                ModelDeployments.id == model_deployment_id,
                ModelDeployments.product_model_id == product_model_id,
            ),
        )
        .join(
            RoutingPolicies,
            RoutingPolicies.model_revision_id == ModelRevisions.id,
        )
        .join(
            PriceBindings,
            and_(
                PriceBindings.model_revision_id == ModelRevisions.id,
                PriceBindings.model_deployment_id == ModelDeployments.id,
            ),
        )
        .join(
            PriceVersions,
            and_(
                PriceVersions.id == PriceBindings.price_version_id,
                PriceVersions.model_revision_id == ModelRevisions.id,
            ),
        )
        .where(
            ModelRevisions.product_model_id == product_model_id,
            RoutingPolicies.strategy == "priority",
            PriceBindings.effective_from <= effective_at,
            (PriceBindings.effective_to.is_(None) | (PriceBindings.effective_to > effective_at)),
            PriceVersions.effective_from <= effective_at,
            (PriceVersions.effective_to.is_(None) | (PriceVersions.effective_to > effective_at)),
        )
        .order_by(
            ModelRevisions.version.desc(),
            RoutingPolicies.version.desc(),
            PriceVersions.version.desc(),
        )
        .limit(1)
    )


async def resolve_accepted_decision(
    session: AsyncSession,
    *,
    product_model_id: UUID,
    model_deployment_id: UUID,
    now: datetime | None = None,
) -> AcceptedDecisionSnapshot | None:
    """Load one complete, currently effective priority-policy decision.

    The route resolver remains responsible for selecting an active deployment
    by priority.  This helper only joins the immutable facts for that selected
    route; it intentionally does not introduce fallback or multi-provider
    selection behavior.
    """

    effective_at = now or datetime.now(UTC)
    row = (
        await session.execute(
            _accepted_decision_statement(
                product_model_id=product_model_id,
                model_deployment_id=model_deployment_id,
                effective_at=effective_at,
            )
        )
    ).first()
    if row is None:
        return None
    revision, policy, price = row
    schema = revision.capability_schema
    if not isinstance(schema, dict) or not isinstance(revision.capability_schema_hash, str):
        return None
    return AcceptedDecisionSnapshot(
        model_revision_id=revision.id,
        model_deployment_id=model_deployment_id,
        routing_policy_id=policy.id,
        price_version_id=price.id,
        price=PriceSnapshot(
            price_version_id=price.id,
            price_key=price.price_key,
            version=int(price.version),
            currency=price.currency,
            unit=price.unit,
            pricing=dict(price.pricing or {}),
        ),
        capability_schema_version=revision.capability_schema_version,
        capability_schema_hash=revision.capability_schema_hash,
        capability_schema=dict(schema),
    )


class CatalogRepository(Protocol):
    async def list_for_tenant(self, tenant_id: UUID) -> Sequence[CatalogRecord]: ...

    async def grant_default_entitlements(
        self, tenant_id: UUID, model_keys: Sequence[str] | None = None
    ) -> int: ...


class SqlAlchemyCatalogRepository:
    """Read/write repository backed by PostgreSQL via SQLAlchemy async ORM."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _catalog_query(self, tenant_id: UUID) -> Select[Any]:
        # Product models are global.  The entitlement join is the authorization
        # boundary: no tenant ID supplied by a client is ever trusted here.
        return (
            select(ProductModels, TenantModelEntitlements, ModelDeployments, ProviderEndpoints)
            .join(
                TenantModelEntitlements,
                and_(
                    TenantModelEntitlements.product_model_id == ProductModels.id,
                    TenantModelEntitlements.tenant_id == tenant_id,
                    TenantModelEntitlements.enabled.is_(True),
                ),
            )
            .outerjoin(
                ModelDeployments,
                ModelDeployments.product_model_id == ProductModels.id,
            )
            .outerjoin(
                ProviderEndpoints,
                ProviderEndpoints.id == ModelDeployments.provider_endpoint_id,
            )
            .where(ProductModels.status == "active")
            .order_by(ProductModels.display_name, ModelDeployments.priority)
        )

    async def list_for_tenant(self, tenant_id: UUID) -> Sequence[CatalogRecord]:
        result = await self.session.execute(self._catalog_query(tenant_id))
        grouped: dict[UUID, CatalogRecord] = {}
        for product, entitlement, deployment, endpoint in result.all():
            product_model = product
            tenant_entitlement = entitlement
            model_deployment = deployment
            provider_endpoint = endpoint
            product_id = product_model.id
            existing = grouped.get(product_id)
            snapshots = list(existing.deployments) if existing else []
            if model_deployment is not None and provider_endpoint is not None:
                snapshots.append(
                    DeploymentSnapshot(
                        status=model_deployment.status,
                        endpoint_status=provider_endpoint.status,
                        provider_model_id=model_deployment.provider_model_id,
                        routing_config=dict(model_deployment.routing_config or {}),
                    )
                )
            if existing is None:
                grouped[product_id] = CatalogRecord(
                    product_model_id=product_id,
                    model_key=product_model.model_key,
                    display_name=product_model.display_name,
                    modality=product_model.modality,
                    task_type=product_model.task_type,
                    product_status=product_model.status,
                    capabilities=dict(product_model.capabilities or {}),
                    pricing_summary=dict(product_model.pricing_summary or {}),
                    description=product_model.description,
                    entitlement_config=dict(tenant_entitlement.config or {}),
                    deployments=tuple(snapshots),
                )
            else:
                grouped[product_id] = CatalogRecord(
                    product_model_id=existing.product_model_id,
                    model_key=existing.model_key,
                    display_name=existing.display_name,
                    modality=existing.modality,
                    task_type=existing.task_type,
                    product_status=existing.product_status,
                    capabilities=existing.capabilities,
                    pricing_summary=existing.pricing_summary,
                    description=existing.description,
                    entitlement_config=existing.entitlement_config,
                    deployments=tuple(snapshots),
                )
        return tuple(grouped.values())

    async def grant_default_entitlements(
        self, tenant_id: UUID, model_keys: Sequence[str] | None = None
    ) -> int:
        """Grant enabled access to seeded products for a newly created tenant.

        The unique constraint makes this safe to retry.  The operation only
        touches product IDs selected from the global catalog and never accepts
        a provider model ID from a caller.
        """

        product_query = select(ProductModels.id).where(ProductModels.status == "active")
        if model_keys:
            product_query = product_query.where(ProductModels.model_key.in_(tuple(model_keys)))
        product_ids = tuple(row[0] for row in (await self.session.execute(product_query)).all())
        if not product_ids:
            return 0

        existing_result = await self.session.execute(
            select(TenantModelEntitlements.product_model_id).where(
                TenantModelEntitlements.tenant_id == tenant_id,
                TenantModelEntitlements.product_model_id.in_(product_ids),
            )
        )
        existing_ids = {row[0] for row in existing_result.all()}
        created = 0
        for product_id in product_ids:
            if product_id in existing_ids:
                continue
            self.session.add(
                TenantModelEntitlements(
                    tenant_id=tenant_id,
                    product_model_id=product_id,
                    enabled=True,
                    config={},
                )
            )
            created += 1
        await self.session.flush()
        return created


SessionFactory = session_factory


async def catalog_session() -> AsyncSession:
    """Compatibility helper for callers that need a short-lived session."""

    return SessionFactory()


__all__ = [
    "AcceptedDecisionSnapshot",
    "CatalogRecord",
    "CatalogRepository",
    "DeploymentSnapshot",
    "SessionFactory",
    "SqlAlchemyCatalogRepository",
    "catalog_session",
    "resolve_accepted_decision",
]
