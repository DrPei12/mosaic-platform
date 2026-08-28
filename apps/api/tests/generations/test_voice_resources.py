from __future__ import annotations

import pytest

from app.generations.voice_resources import (
    VoiceResourceUnavailable,
    resolve_audio_voice_binding,
)


def test_standard_audio_route_uses_only_trusted_default_voice() -> None:
    binding = resolve_audio_voice_binding(
        provider_model_id="qwen3-tts-flash",
        routing_config={"live_modality": "audio", "default_voice": "Cherry"},
        entitlement_config={},
    )

    assert binding is not None
    assert binding.target_model == "qwen3-tts-flash"
    assert binding.provider_voice_id == "Cherry"


def test_tenant_voice_resource_requires_active_exact_target_binding() -> None:
    route = {"live_modality": "audio", "voice_resource_required": True}
    binding = resolve_audio_voice_binding(
        provider_model_id="qwen3-tts-vd-2026-01-26",
        routing_config=route,
        entitlement_config={
            "voice_resource": {
                "status": "active",
                "target_model": "qwen3-tts-vd-2026-01-26",
                "provider_voice_id": "private-voice-id",
            }
        },
    )

    assert binding is not None
    assert binding.provider_voice_id == "private-voice-id"
    assert "private-voice-id" not in repr(binding)

    invalid_resources = (
        {},
        {"voice_resource": {"status": "revoked"}},
        {
            "voice_resource": {
                "status": "active",
                "target_model": "qwen3-tts-vc-2026-01-22",
                "provider_voice_id": "private-voice-id",
            }
        },
        {
            "voice_resource": {
                "status": "active",
                "target_model": "qwen3-tts-vd-2026-01-26",
                "provider_voice_id": "",
            }
        },
    )
    for entitlement in invalid_resources:
        with pytest.raises(VoiceResourceUnavailable) as error:
            resolve_audio_voice_binding(
                provider_model_id="qwen3-tts-vd-2026-01-26",
                routing_config=route,
                entitlement_config=entitlement,
            )
        assert "private-voice-id" not in str(error.value)


def test_non_audio_route_does_not_require_a_voice() -> None:
    assert resolve_audio_voice_binding(
        provider_model_id="qwen-image-3.0-pro",
        routing_config={"live_modality": "image"},
        entitlement_config={},
    ) is None
