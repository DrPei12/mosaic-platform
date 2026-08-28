"""Fail-closed resolution for provider voice resources.

Provider voice identifiers are credentials-like routing data.  They are kept
inside tenant entitlement configuration and are never accepted from, or
returned to, a public generation request.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.generations.ports import AudioVoiceBinding


class VoiceResourceUnavailable(ValueError):
    """The selected audio deployment has no valid server-owned voice."""


def resolve_audio_voice_binding(
    *,
    provider_model_id: str,
    routing_config: Mapping[str, Any],
    entitlement_config: Mapping[str, Any],
) -> AudioVoiceBinding | None:
    """Return the trusted voice for an audio route, or fail closed.

    Non-audio deployments intentionally return ``None``.  Standard TTS routes
    must declare an internal ``default_voice``; VoiceDesign and CustomVoice
    routes must have an active tenant resource bound to the exact target model.
    """

    if routing_config.get("live_modality") != "audio":
        return None

    if routing_config.get("voice_resource_required") is True:
        resource = entitlement_config.get("voice_resource")
        if not isinstance(resource, Mapping):
            raise VoiceResourceUnavailable("voice resource is unavailable")
        status = resource.get("status")
        target_model = resource.get("target_model")
        provider_voice_id = resource.get("provider_voice_id")
        if (
            status != "active"
            or target_model != provider_model_id
            or not isinstance(provider_voice_id, str)
            or not provider_voice_id.strip()
        ):
            raise VoiceResourceUnavailable("voice resource is unavailable")
        return AudioVoiceBinding(
            target_model=provider_model_id,
            provider_voice_id=provider_voice_id.strip(),
        )

    default_voice = routing_config.get("default_voice")
    if not isinstance(default_voice, str) or not default_voice.strip():
        raise VoiceResourceUnavailable("default voice is unavailable")
    return AudioVoiceBinding(
        target_model=provider_model_id,
        provider_voice_id=default_voice.strip(),
    )


__all__ = [
    "VoiceResourceUnavailable",
    "resolve_audio_voice_binding",
]
