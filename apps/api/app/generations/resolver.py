"""Trusted deployment-to-DashScope provider resolution."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.generations.errors import GenerationInfrastructureError
from app.generations.ports import ProviderPorts, ProviderResolverPort
from app.generations.voice_resources import (
    VoiceResourceUnavailable,
    resolve_audio_voice_binding,
)
from app.infrastructure.models import (
    ModelDeployments,
    ProductModels,
    ProviderEndpoints,
    TenantModelEntitlements,
)
from app.providers import DashScopeProvider
from app.providers.config import (
    DEFAULT_DASHSCOPE_NATIVE_BASE_URL,
    DEFAULT_DASHSCOPE_TEXT_BASE_URL,
    ProviderSettings,
)

_TRUSTED_SECRET_REF = "env:DASHSCOPE_API_KEY"
_TRUSTED_PROVIDER_NAMES = frozenset({"bailian", "dashscope"})


class SqlAlchemyDashScopeProviderResolver(ProviderResolverPort):
    """Resolve only active, catalog-owned DashScope deployments."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def resolve(self, *, deployment_id: UUID, tenant_id: UUID) -> ProviderPorts:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(
                        ModelDeployments,
                        ProviderEndpoints,
                        TenantModelEntitlements,
                    )
                    .join(
                        ProviderEndpoints,
                        ProviderEndpoints.id == ModelDeployments.provider_endpoint_id,
                    )
                    .join(
                        ProductModels,
                        ProductModels.id == ModelDeployments.product_model_id,
                    )
                    .join(
                        TenantModelEntitlements,
                        and_(
                            TenantModelEntitlements.product_model_id == ProductModels.id,
                            TenantModelEntitlements.tenant_id == tenant_id,
                            TenantModelEntitlements.enabled.is_(True),
                        ),
                    )
                    .where(
                        ModelDeployments.id == deployment_id,
                        ModelDeployments.status == "active",
                        ProviderEndpoints.status == "active",
                    )
                )
            ).first()
        if row is None:
            raise GenerationInfrastructureError("GENERATION_PROVIDER_ROUTE_UNAVAILABLE")
        deployment, endpoint, entitlement = row
        if (
            endpoint.provider_name not in _TRUSTED_PROVIDER_NAMES
            or endpoint.secret_ref != _TRUSTED_SECRET_REF
            or endpoint.protocol not in {"openai_compatible", "dashscope_http", "dashscope_async"}
        ):
            raise GenerationInfrastructureError("GENERATION_PROVIDER_ROUTE_UNAVAILABLE")
        try:
            settings = _provider_settings(endpoint.protocol, endpoint.base_url)
            provider = DashScopeProvider.from_env(settings=settings)
        except Exception as exc:
            raise GenerationInfrastructureError("GENERATION_PROVIDER_NOT_CONFIGURED") from exc
        if endpoint.protocol == "openai_compatible":
            return ProviderPorts(
                text=provider,
                provider_model_id=deployment.provider_model_id,
                provider_name="dashscope",
            )
        try:
            audio_voice = resolve_audio_voice_binding(
                provider_model_id=deployment.provider_model_id,
                routing_config=dict(deployment.routing_config or {}),
                entitlement_config=dict(entitlement.config or {}),
            )
        except VoiceResourceUnavailable as exc:
            raise GenerationInfrastructureError(
                "GENERATION_PROVIDER_ROUTE_UNAVAILABLE"
            ) from exc
        return ProviderPorts(
            image=provider,
            video=provider,
            audio=provider,
            provider_model_id=deployment.provider_model_id,
            provider_name="dashscope",
            audio_voice=audio_voice,
        )


def _provider_settings(protocol: str, base_url: str) -> ProviderSettings:
    if protocol == "openai_compatible":
        return ProviderSettings(
            dashscope_text_base_url=base_url,
            dashscope_native_base_url=DEFAULT_DASHSCOPE_NATIVE_BASE_URL,
        )
    return ProviderSettings(
        dashscope_text_base_url=DEFAULT_DASHSCOPE_TEXT_BASE_URL,
        dashscope_native_base_url=base_url,
    )


DashScopeProviderResolver = SqlAlchemyDashScopeProviderResolver


__all__ = ["DashScopeProviderResolver", "SqlAlchemyDashScopeProviderResolver"]
