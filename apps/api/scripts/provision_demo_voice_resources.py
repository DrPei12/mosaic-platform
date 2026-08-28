"""Provision and bind real Qwen3-TTS demo voices without exposing their IDs.

This operator-only script creates the two provider resources required by the
VoiceDesign and CustomVoice product routes, verifies synthesis on the exact
target model, then stores the resource binding in the selected tenant's
entitlement configuration.  It is idempotent after a successful binding.

The DashScope API key is read only from ``DASHSCOPE_API_KEY``.  Provider voice
IDs and signed artifact URLs are never printed or written to repository files.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
from sqlalchemy import and_, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.engine import CursorResult

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.database import session_factory
from app.infrastructure.models import (
    ModelDeployments,
    ProductModels,
    ProviderEndpoints,
    TenantModelEntitlements,
    Tenants,
)
from app.providers.config import ProviderCredential
from app.providers.ports import RemoteAsset

CUSTOMIZATION_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
)
SYNTHESIS_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
    "multimodal-generation/generation"
)
VOICE_TARGETS = {
    "qwen3-tts-voice-design": "qwen3-tts-vd-2026-01-26",
    "qwen3-tts-custom-voice": "qwen3-tts-vc-2026-01-22",
}
CLONE_SAMPLE_TEXT = (
    "欢迎体验多模态人工智能平台。这里是一段用于验证语音生成与音色绑定的清晰普通话样本，"
    "语速自然、发音连贯，并包含足够长度的连续语音，以便完成真实的声音资源创建测试。"
)
LIVE_CHECK_TEXT = "这是一次真实语音模型调用验证。"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Provision tenant Qwen3-TTS voices")
    parser.add_argument("--tenant", default="mosaic-demo")
    parser.add_argument(
        "--confirm-provider-charges",
        action="store_true",
        help="required before any provider POST, including paid revalidation",
    )
    parser.add_argument(
        "--revalidate",
        action="store_true",
        help="repeat paid synthesis checks for already-active bindings",
    )
    return parser


def _provider_headers(credential: ProviderCredential) -> dict[str, str]:
    return {
        "Authorization": credential.authorization_header(),
        "Content-Type": "application/json",
    }


async def _post_json(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    response = await client.post(url, headers=dict(headers), json=dict(payload))
    if response.status_code != 200:
        raise RuntimeError(f"provider request failed with HTTP {response.status_code}")
    result = response.json()
    if not isinstance(result, Mapping):
        raise TypeError("provider returned an invalid response")
    return result


def _output(result: Mapping[str, Any]) -> Mapping[str, Any]:
    value = result.get("output")
    if not isinstance(value, Mapping):
        raise TypeError("provider response has no output")
    return value


def _voice_id(result: Mapping[str, Any]) -> str:
    voice = _output(result).get("voice")
    if not isinstance(voice, str) or not voice.strip():
        raise RuntimeError("provider response has no voice resource")
    return voice.strip()


def _audio_url(result: Mapping[str, Any]) -> str:
    audio = _output(result).get("audio")
    if not isinstance(audio, Mapping):
        raise TypeError("provider response has no audio")
    url = audio.get("url")
    if not isinstance(url, str):
        raise TypeError("provider response has no downloadable audio")
    try:
        return RemoteAsset.from_url(url).url
    except ValueError as error:
        raise RuntimeError("provider response has no downloadable audio") from error


def _request_id_present(result: Mapping[str, Any]) -> bool:
    request_id = result.get("request_id")
    if isinstance(request_id, str) and request_id.strip():
        return True
    output = result.get("output")
    return isinstance(output, Mapping) and isinstance(output.get("request_id"), str)


async def _synthesize(
    client: httpx.AsyncClient,
    *,
    headers: Mapping[str, str],
    model: str,
    voice: str,
    text: str,
) -> Mapping[str, Any]:
    result = await _post_json(
        client,
        url=SYNTHESIS_URL,
        headers=headers,
        payload={
            "model": model,
            "input": {
                "text": text,
                "voice": voice,
                "language_type": "Chinese",
            },
        },
    )
    _audio_url(result)
    if not _request_id_present(result):
        raise RuntimeError("provider response has no request ID")
    return result


async def _create_voice_design(
    client: httpx.AsyncClient,
    *,
    headers: Mapping[str, str],
) -> str:
    suffix = secrets.token_hex(3)
    result = await _post_json(
        client,
        url=CUSTOMIZATION_URL,
        headers=headers,
        payload={
            "model": "qwen-voice-design",
            "input": {
                "action": "create",
                "target_model": VOICE_TARGETS["qwen3-tts-voice-design"],
                "preferred_name": f"mosvd{suffix}",
                "voice_prompt": (
                    "一位二十多岁的自然女声，音色清澈温暖，语速适中，吐字清晰，情绪亲切克制，"
                    "适合产品讲解、知识播报和智能助手。"
                ),
                "preview_text": "欢迎使用多模态人工智能平台，让我们开始今天的创作。",
            },
            "parameters": {"sample_rate": 24000, "response_format": "wav"},
        },
    )
    return _voice_id(result)


async def _create_custom_voice(
    client: httpx.AsyncClient,
    *,
    headers: Mapping[str, str],
) -> str:
    sample = await _synthesize(
        client,
        headers=headers,
        model="qwen3-tts-flash",
        voice="Cherry",
        text=CLONE_SAMPLE_TEXT,
    )
    suffix = secrets.token_hex(3)
    result = await _post_json(
        client,
        url=CUSTOMIZATION_URL,
        headers=headers,
        payload={
            "model": "qwen-voice-enrollment",
            "input": {
                "action": "create",
                "target_model": VOICE_TARGETS["qwen3-tts-custom-voice"],
                "preferred_name": f"mosvc{suffix}",
                "audio": {"data": _audio_url(sample)},
            },
        },
    )
    return _voice_id(result)


def _stored_voice(
    config: Mapping[str, Any],
    *,
    target_model: str,
) -> tuple[str | None, bool]:
    resource = config.get("voice_resource")
    if not isinstance(resource, Mapping):
        return None, False
    voice = resource.get("provider_voice_id")
    if (
        resource.get("status") not in {"active", "provisioning"}
        or resource.get("target_model") != target_model
        or not isinstance(voice, str)
        or not voice.strip()
    ):
        return None, False
    return voice.strip(), resource.get("status") == "active"


async def _load_tenant_bindings(
    tenant_slug: str,
) -> tuple[UUID, dict[str, tuple[UUID, UUID, UUID, str | None, bool]]]:
    async with session_factory() as session:
        tenant = (
            await session.execute(
                select(Tenants).where(Tenants.slug == tenant_slug, Tenants.status == "active")
            )
        ).scalar_one_or_none()
        if tenant is None:
            raise RuntimeError("active tenant was not found")
        rows = (
            await session.execute(
                select(
                    ProductModels,
                    TenantModelEntitlements,
                    ModelDeployments,
                    ProviderEndpoints,
                )
                .join(
                    TenantModelEntitlements,
                    and_(
                        TenantModelEntitlements.product_model_id == ProductModels.id,
                        TenantModelEntitlements.tenant_id == tenant.id,
                        TenantModelEntitlements.enabled.is_(True),
                    ),
                )
                .join(
                    ModelDeployments,
                    ModelDeployments.product_model_id == ProductModels.id,
                )
                .join(
                    ProviderEndpoints,
                    ProviderEndpoints.id == ModelDeployments.provider_endpoint_id,
                )
                .where(
                    ProductModels.model_key.in_(tuple(VOICE_TARGETS)),
                    ProviderEndpoints.endpoint_key == "bailian-dashscope-native",
                )
            )
        ).all()
        by_key: dict[str, tuple[UUID, UUID, UUID, str | None, bool]] = {}
        for product, entitlement, deployment, endpoint in rows:
            target_model = VOICE_TARGETS[product.model_key]
            if deployment.provider_model_id != target_model:
                continue
            if product.model_key in by_key:
                raise RuntimeError("tenant voice deployment is ambiguous")
            voice, active = _stored_voice(
                dict(entitlement.config or {}),
                target_model=target_model,
            )
            by_key[product.model_key] = (
                entitlement.id,
                deployment.id,
                endpoint.id,
                voice,
                active,
            )
        if set(by_key) != set(VOICE_TARGETS):
            raise RuntimeError("tenant voice entitlements are incomplete")
        return tenant.id, by_key


async def _persist_bindings(
    *,
    tenant_id: UUID,
    rows: Mapping[str, tuple[UUID, UUID, UUID, str | None, bool]],
    voices: Mapping[str, str],
) -> None:
    async with session_factory() as session, session.begin():
        for model_key, target_model in VOICE_TARGETS.items():
            entitlement_id, deployment_id, _, _, _ = rows[model_key]
            entitlement = (
                await session.execute(
                    select(TenantModelEntitlements)
                    .where(
                        TenantModelEntitlements.id == entitlement_id,
                        TenantModelEntitlements.tenant_id == tenant_id,
                        TenantModelEntitlements.enabled.is_(True),
                    )
                    .with_for_update()
                )
            ).scalar_one()
            current = dict(entitlement.config or {})
            current["voice_resource"] = {
                "status": "active",
                "target_model": target_model,
                "provider_voice_id": voices[model_key],
            }
            entitlement.config = current
            deployment_result = await session.execute(
                update(ModelDeployments)
                .where(ModelDeployments.id == deployment_id)
                .values(status="active")
            )
            if cast(CursorResult[Any], deployment_result).rowcount != 1:
                raise RuntimeError("voice deployment activation failed")
        endpoint_ids = {row[2] for row in rows.values()}
        endpoint_result = await session.execute(
            update(ProviderEndpoints)
            .where(ProviderEndpoints.id.in_(endpoint_ids))
            .values(status="active")
        )
        if cast(CursorResult[Any], endpoint_result).rowcount != len(endpoint_ids):
            raise RuntimeError("voice endpoint activation failed")


async def _persist_provisioning_resource(
    *,
    tenant_id: UUID,
    row: tuple[UUID, UUID, UUID, str | None, bool],
    target_model: str,
    voice: str,
) -> None:
    entitlement_id, _, _, _, _ = row
    async with session_factory() as session, session.begin():
        entitlement = (
            await session.execute(
                select(TenantModelEntitlements)
                .where(
                    TenantModelEntitlements.id == entitlement_id,
                    TenantModelEntitlements.tenant_id == tenant_id,
                    TenantModelEntitlements.enabled.is_(True),
                )
                .with_for_update()
            )
        ).scalar_one()
        current = dict(entitlement.config or {})
        current["voice_resource"] = {
            "status": "provisioning",
            "target_model": target_model,
            "provider_voice_id": voice,
        }
        entitlement.config = current


@asynccontextmanager
async def _tenant_provision_lock(tenant_slug: str) -> AsyncIterator[None]:
    async with session_factory() as session, session.begin():
        acquired = await session.scalar(
            sql_text(
                "SELECT pg_try_advisory_xact_lock(hashtext(:lock_name))"
            ),
            {"lock_name": f"mosaic:voice-provision:{tenant_slug}"},
        )
        if acquired is not True:
            raise RuntimeError("voice provisioning is already running for this tenant")
        yield


async def _provision_locked(
    *,
    tenant_slug: str,
    confirm_provider_charges: bool,
    revalidate: bool,
) -> dict[str, Any]:
    tenant_id, rows = await _load_tenant_bindings(tenant_slug)
    voices: dict[str, str] = {
        key: voice for key, (_, _, _, voice, _) in rows.items() if voice is not None
    }
    missing = set(VOICE_TARGETS) - set(voices)
    all_active = all(row[4] for row in rows.values())
    performed_live_validation = bool(missing) or not all_active or revalidate
    if performed_live_validation and not confirm_provider_charges:
        raise RuntimeError("provider charge confirmation is required")

    if performed_live_validation:
        headers = _provider_headers(ProviderCredential.from_env())
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0), follow_redirects=True) as client:
            if "qwen3-tts-custom-voice" in missing:
                voice = await _create_custom_voice(client, headers=headers)
                voices["qwen3-tts-custom-voice"] = voice
                await _persist_provisioning_resource(
                    tenant_id=tenant_id,
                    row=rows["qwen3-tts-custom-voice"],
                    target_model=VOICE_TARGETS["qwen3-tts-custom-voice"],
                    voice=voice,
                )
            if "qwen3-tts-voice-design" in missing:
                voice = await _create_voice_design(client, headers=headers)
                voices["qwen3-tts-voice-design"] = voice
                await _persist_provisioning_resource(
                    tenant_id=tenant_id,
                    row=rows["qwen3-tts-voice-design"],
                    target_model=VOICE_TARGETS["qwen3-tts-voice-design"],
                    voice=voice,
                )
            for model_key, target_model in VOICE_TARGETS.items():
                await _synthesize(
                    client,
                    headers=headers,
                    model=target_model,
                    voice=voices[model_key],
                    text=LIVE_CHECK_TEXT,
                )

    await _persist_bindings(
        tenant_id=tenant_id,
        rows=rows,
        voices=voices,
    )
    return {
        "status": "ok",
        "tenant": tenant_slug,
        "models": [
            {
                "product_model_id": key,
                "live_verified": performed_live_validation,
                "binding_reused": key not in missing,
            }
            for key in sorted(VOICE_TARGETS)
        ],
        "provider_voice_ids_exposed": False,
    }


async def provision(
    *,
    tenant_slug: str,
    confirm_provider_charges: bool,
    revalidate: bool = False,
) -> dict[str, Any]:
    async with _tenant_provision_lock(tenant_slug):
        return await _provision_locked(
            tenant_slug=tenant_slug,
            confirm_provider_charges=confirm_provider_charges,
            revalidate=revalidate,
        )


async def _run(args: argparse.Namespace) -> None:
    result = await provision(
        tenant_slug=args.tenant,
        confirm_provider_charges=args.confirm_provider_charges,
        revalidate=args.revalidate,
    )
    print(json.dumps(result, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        asyncio.run(_run(args))
    except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"voice resource provisioning failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["VOICE_TARGETS", "main", "provision"]
