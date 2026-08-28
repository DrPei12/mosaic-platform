"""Canonical, secret-free product routing manifest.

The manifest is deliberately data-only.  Provider model IDs are internal
routing data and never flow through the public catalog contract.  All seeded
routes start disabled/degraded until the controlled live-evidence activation
step is run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final

REQUIRED_LIVE_MODALITIES: Final[frozenset[str]] = frozenset(
    {"text", "image", "video", "audio"}
)

DEFAULT_SECRET_REF: Final[str] = "env:DASHSCOPE_API_KEY"
OPENAI_COMPATIBLE_BASE_URL: Final[str] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_NATIVE_BASE_URL: Final[str] = "https://dashscope.aliyuncs.com/api/v1"
CAPABILITY_SCHEMA_VERSION: Final[int] = 1
PRICE_EFFECTIVE_FROM: Final[str] = "2026-08-26T00:00:00+00:00"

# The local release tariff is intentionally integer-only: all amounts are
# hundredths of one internal point (PTS), and each component is charged per
# raw normalized usage unit.  The hold is a bounded authorization ceiling;
# capture never charges above it.
_LOCAL_TARIFF_BY_MODALITY: Final[dict[str, dict[str, object]]] = {
    "text": {
        "reservation_minor": 100_000,
        "minimum_charge_minor": 1,
        "components": {"input_tokens": 1, "output_tokens": 2},
    },
    "image": {
        "reservation_minor": 10_000,
        "minimum_charge_minor": 100,
        "components": {"image_count": 1_000},
    },
    "video": {
        "reservation_minor": 100_000,
        "minimum_charge_minor": 500,
        "components": {"video_seconds": 1_000},
    },
    "audio": {
        "reservation_minor": 50_000,
        "minimum_charge_minor": 1,
        "components": {"character_count": 1},
    },
}


def canonical_json_bytes(value: object) -> bytes:
    """Serialize JSON metadata identically across seed runs and processes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def capability_schema_hash(schema: Mapping[str, Any]) -> str:
    """Return the stable SHA-256 identity of one capability schema."""

    return hashlib.sha256(canonical_json_bytes(schema)).hexdigest()

# Tuples of plain dictionaries make the serialized manifest deterministic and
# easy to inspect in tests, while keeping mutation out of runtime code.
ENDPOINTS: Final[tuple[dict[str, object], ...]] = (
    {
        "endpoint_key": "bailian-openai-compatible",
        "provider_name": "bailian",
        "protocol": "openai_compatible",
        "base_url": OPENAI_COMPATIBLE_BASE_URL,
        "secret_ref": DEFAULT_SECRET_REF,
        "status": "degraded",
        "timeout_ms": 60_000,
        "config": {"region": "beijing", "purpose": "text-chat"},
    },
    {
        "endpoint_key": "bailian-dashscope-native",
        "provider_name": "bailian",
        # DashScope native HTTP serves both synchronous image/TTS and async
        # video.  The per-deployment routing_config carries async semantics.
        "protocol": "dashscope_http",
        "base_url": DASHSCOPE_NATIVE_BASE_URL,
        "secret_ref": DEFAULT_SECRET_REF,
        "status": "degraded",
        "timeout_ms": 120_000,
        "config": {"region": "beijing", "purpose": "media-generation"},
    },
)


def _public(
    capabilities: list[str],
    collections: list[str],
    *,
    input_schema: dict[str, object] | None = None,
    voice_resource_required: bool = False,
    execution_policy: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "public_capabilities": capabilities,
        "collections": collections,
    }
    if input_schema is not None:
        payload["input_schema"] = input_schema
    if voice_resource_required:
        payload["voice_resource_required"] = True
    if execution_policy is not None:
        payload["execution_policy"] = execution_policy
    return payload


PRODUCTS: Final[tuple[dict[str, object], ...]] = (
    {
        "model_key": "qwen-3-5-plus",
        "display_name": "Qwen 3.5 Plus",
        "modality": "text",
        "task_type": "chat",
        "status": "active",
        "capabilities": _public(
            ["多轮对话", "流式输出", "长上下文"],
            ["featured", "popular"],
            input_schema={"messages": {"type": "array"}},
        ),
        "pricing_summary": {"zh-CN": "按实际用量计费"},
        "description": "面向真实生产调用的通用文本对话模型。",
    },
    {
        "model_key": "qwen-image-3-0-pro",
        "display_name": "Qwen Image 3.0 Pro",
        "modality": "image",
        "task_type": "text_to_image",
        "status": "active",
        "capabilities": _public(
            ["文字生成图像", "高分辨率", "风格控制"],
            ["featured", "popular"],
            input_schema={"prompt": {"type": "string"}},
        ),
        "pricing_summary": {"zh-CN": "按图片生成量计费"},
        "description": "用于真实图片生成任务的高质量图像模型。",
    },
    {
        "model_key": "wan-2-7",
        "display_name": "Wan 2.7",
        "modality": "video",
        "task_type": "text_to_video",
        "status": "active",
        "capabilities": _public(
            ["文字生成视频", "镜头运动", "异步任务"],
            ["featured", "new"],
            input_schema={"prompt": {"type": "string"}},
        ),
        "pricing_summary": {"zh-CN": "按视频时长计费"},
        "description": "通过异步任务生成短视频内容。",
    },
    {
        "model_key": "qwen3-tts-base",
        "display_name": "Qwen3-TTS 1.7B Base",
        "modality": "audio",
        "task_type": "tts",
        "status": "active",
        "capabilities": _public(
            ["文字转语音", "多语言", "自然语音"],
            ["featured", "popular"],
            input_schema={"text": {"type": "string"}},
            execution_policy="unsupported",
        ),
        "pricing_summary": {"zh-CN": "按字符数计费"},
        "description": "面向真实语音合成任务的基础语音模型。",
    },
    {
        "model_key": "qwen3-tts-flash",
        "display_name": "Qwen3-TTS Flash",
        "modality": "audio",
        "task_type": "tts",
        "status": "active",
        "capabilities": _public(
            ["文字转语音", "多语言", "自然语音"],
            ["featured", "popular"],
            input_schema={"text": {"type": "string"}},
        ),
        "pricing_summary": {"zh-CN": "按字符数计费"},
        "description": "百炼 qwen3-tts-flash 的真实语音合成产品路由。",
    },
    {
        "model_key": "qwen3-tts-voice-design",
        "display_name": "Qwen3-TTS 1.7B VoiceDesign",
        "modality": "audio",
        "task_type": "tts",
        "status": "active",
        "capabilities": _public(
            ["文字转语音", "声音设计", "异步任务"],
            ["new"],
            input_schema={"text": {"type": "string"}},
            voice_resource_required=True,
        ),
        "pricing_summary": {"zh-CN": "按字符数计费"},
        "description": "可按声音设定生成语音；需要先创建租户声音资源。",
    },
    {
        "model_key": "qwen3-tts-custom-voice",
        "display_name": "Qwen3-TTS 1.7B CustomVoice",
        "modality": "audio",
        "task_type": "tts",
        "status": "active",
        "capabilities": _public(
            ["文字转语音", "自定义音色", "异步任务"],
            ["new"],
            input_schema={"text": {"type": "string"}},
            voice_resource_required=True,
        ),
        "pricing_summary": {"zh-CN": "按字符数计费"},
        "description": "使用租户已创建的声音资源合成语音。",
    },
)


DEPLOYMENTS: Final[tuple[dict[str, object], ...]] = (
    {
        "model_key": "qwen-3-5-plus",
        "endpoint_key": "bailian-openai-compatible",
        "provider_model_id": "qwen3.5-plus",
        "status": "disabled",
        "priority": 10,
        "concurrency_limit": 32,
        "routing_config": {"live_modality": "text"},
    },
    {
        "model_key": "qwen-image-3-0-pro",
        "endpoint_key": "bailian-dashscope-native",
        "provider_model_id": "qwen-image-3.0-pro",
        "status": "disabled",
        "priority": 10,
        "concurrency_limit": 8,
        "routing_config": {"live_modality": "image"},
    },
    {
        "model_key": "wan-2-7",
        "endpoint_key": "bailian-dashscope-native",
        "provider_model_id": "wan2.7-t2v",
        "status": "disabled",
        "priority": 10,
        "concurrency_limit": 4,
        "routing_config": {"live_modality": "video", "async": True},
    },
    {
        "model_key": "qwen3-tts-flash",
        "endpoint_key": "bailian-dashscope-native",
        "provider_model_id": "qwen3-tts-flash",
        "status": "disabled",
        "priority": 10,
        "concurrency_limit": 8,
        "routing_config": {"live_modality": "audio", "default_voice": "Cherry"},
    },
    {
        "model_key": "qwen3-tts-voice-design",
        "endpoint_key": "bailian-dashscope-native",
        "provider_model_id": "qwen3-tts-vd-2026-01-26",
        "status": "disabled",
        "priority": 20,
        "concurrency_limit": 4,
        "routing_config": {"live_modality": "audio", "voice_resource_required": True},
    },
    {
        "model_key": "qwen3-tts-custom-voice",
        "endpoint_key": "bailian-dashscope-native",
        "provider_model_id": "qwen3-tts-vc-2026-01-22",
        "status": "disabled",
        "priority": 20,
        "concurrency_limit": 4,
        "routing_config": {"live_modality": "audio", "voice_resource_required": True},
    },
)


def _capability_schema(product: Mapping[str, object]) -> dict[str, Any]:
    raw = product.get("capabilities")
    if not isinstance(raw, dict):
        raise TypeError(f"product {product.get('model_key')!r} has no object capabilities")
    return dict(raw)


MODEL_REVISIONS: Final[tuple[dict[str, object], ...]] = tuple(
    {
        "model_key": product["model_key"],
        "version": 1,
        "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
        "capability_schema": schema,
        "capability_schema_hash": capability_schema_hash(schema),
    }
    for product in PRODUCTS
    for schema in (_capability_schema(product),)
)


ROUTING_POLICIES: Final[tuple[dict[str, object], ...]] = tuple(
    {
        "model_key": product["model_key"],
        "policy_key": f"{product['model_key']}:priority-v1",
        "version": 1,
        "strategy": "priority",
        "config": {
            "eligible_deployment_status": "active",
            "eligible_endpoint_status": "active",
            "order_by": ["priority", "created_at", "id"],
            "direction": "asc",
        },
    }
    for product in PRODUCTS
)


PRICE_VERSIONS: Final[tuple[dict[str, object], ...]] = tuple(
    {
        "model_key": product["model_key"],
        "price_key": f"{product['model_key']}:local-v2",
        "version": 2,
        "currency": "PTS",
        "unit": "local_metered_usage",
        "pricing": {
            "schema": "local_tariff_v1",
            "currency": "PTS",
            "rounding": "integer_sum",
            **_LOCAL_TARIFF_BY_MODALITY[str(product["modality"])],
        },
        "effective_from": PRICE_EFFECTIVE_FROM,
        "effective_to": None,
    }
    for product in PRODUCTS
)


MANIFEST: Final[dict[str, tuple[dict[str, object], ...]]] = {
    "endpoints": ENDPOINTS,
    "products": PRODUCTS,
    "deployments": DEPLOYMENTS,
    "model_revisions": MODEL_REVISIONS,
    "routing_policies": ROUTING_POLICIES,
    "price_versions": PRICE_VERSIONS,
}


def manifest_digest() -> str:
    """Return a reproducible identity for the complete secret-free manifest."""

    return hashlib.sha256(canonical_json_bytes(MANIFEST)).hexdigest()


def manifest_model_keys() -> frozenset[str]:
    """Return product keys in deterministic order-independent form."""

    return frozenset(str(item["model_key"]) for item in PRODUCTS)


__all__ = [
    "CAPABILITY_SCHEMA_VERSION",
    "DASHSCOPE_NATIVE_BASE_URL",
    "DEFAULT_SECRET_REF",
    "DEPLOYMENTS",
    "ENDPOINTS",
    "MANIFEST",
    "MODEL_REVISIONS",
    "OPENAI_COMPATIBLE_BASE_URL",
    "PRICE_EFFECTIVE_FROM",
    "PRICE_VERSIONS",
    "PRODUCTS",
    "REQUIRED_LIVE_MODALITIES",
    "ROUTING_POLICIES",
    "canonical_json_bytes",
    "capability_schema_hash",
    "manifest_digest",
    "manifest_model_keys",
]
