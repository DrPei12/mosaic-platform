from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Self
from uuid import uuid4

import httpx
import pytest

from app.catalog import live_evidence
from app.catalog.manifest import manifest_digest
from app.providers.errors import ProviderConfigurationError
from scripts import (
    full_stack_live_smoke,
    provider_smoke,
    provision_demo_voice_resources,
    verify_live_evidence,
)

HMAC_KEY = "unit-test-live-evidence-key-123456"
SMOKE_SCRIPT_PATH = Path(provider_smoke.__file__).resolve()


def _test_source_facts() -> dict[str, object]:
    return {
        "source_commit": "a" * 40,
        "catalog_manifest_digest": manifest_digest(),
        "smoke_script_sha256": "b" * 64,
        "source_tree_clean": True,
    }


def test_live_evidence_facts_fail_closed_for_dirty_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        if "status" in command:
            return SimpleNamespace(stdout=" M apps/api/app/catalog/manifest.py\n")
        return SimpleNamespace(stdout="a" * 40)

    monkeypatch.setattr(live_evidence.subprocess, "run", fake_run)

    with pytest.raises(live_evidence.LiveEvidenceError, match="clean"):
        live_evidence.current_live_evidence_facts(SMOKE_SCRIPT_PATH)


def test_live_evidence_facts_include_clean_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        if "status" in command:
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout="a" * 40)

    monkeypatch.setattr(live_evidence.subprocess, "run", fake_run)

    facts = live_evidence.current_live_evidence_facts(SMOKE_SCRIPT_PATH)

    assert facts == {
        "source_commit": "a" * 40,
        "catalog_manifest_digest": manifest_digest(),
        "smoke_script_sha256": live_evidence.sha256_file(SMOKE_SCRIPT_PATH),
        "source_tree_clean": True,
    }


def test_container_source_facts_use_injected_immutable_build_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(live_evidence.SOURCE_COMMIT_ENV, "c" * 40)
    monkeypatch.setenv(live_evidence.SOURCE_TREE_CLEAN_ENV, "true")

    def unexpected_git(*_: object, **__: object) -> object:
        raise AssertionError("container provenance must not require .git")

    monkeypatch.setattr(live_evidence.subprocess, "run", unexpected_git)

    facts = live_evidence.current_live_evidence_facts(SMOKE_SCRIPT_PATH)

    assert facts["source_commit"] == "c" * 40
    assert facts["source_tree_clean"] is True


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (live_evidence.SOURCE_COMMIT_ENV, "local"),
        (live_evidence.SOURCE_TREE_CLEAN_ENV, "unknown"),
    ],
)
def test_invalid_container_source_facts_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    if name == live_evidence.SOURCE_COMMIT_ENV:
        with pytest.raises(live_evidence.LiveEvidenceError):
            live_evidence.current_source_commit(SMOKE_SCRIPT_PATH)
    else:
        with pytest.raises(live_evidence.LiveEvidenceError):
            live_evidence.source_tree_clean(SMOKE_SCRIPT_PATH)


def test_live_evidence_integrity_rejects_tampered_sources_and_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(live_evidence.LIVE_EVIDENCE_HMAC_KEY_ENV, HMAC_KEY)
    monkeypatch.setattr(
        live_evidence,
        "current_live_evidence_facts",
        lambda _path: _test_source_facts(),
    )
    evidence = live_evidence.bind_live_evidence(
        {"live": True, "status": "ok", "checks": []},
        smoke_script_path=SMOKE_SCRIPT_PATH,
        key=HMAC_KEY,
    )

    live_evidence.verify_live_evidence_integrity(
        evidence,
        smoke_script_path=SMOKE_SCRIPT_PATH,
    )
    for field, value in {
        "source_commit": "c" * 40,
        "catalog_manifest_digest": "c" * 64,
        "smoke_script_sha256": "c" * 64,
        "source_tree_clean": False,
    }.items():
        tampered = {**evidence, field: value}
        with pytest.raises(live_evidence.LiveEvidenceError):
            live_evidence.verify_live_evidence_integrity(
                tampered,
                smoke_script_path=SMOKE_SCRIPT_PATH,
            )

    tampered_hmac = {**evidence, live_evidence.LIVE_EVIDENCE_HMAC_FIELD: "0" * 64}
    with pytest.raises(live_evidence.LiveEvidenceError):
        live_evidence.verify_live_evidence_integrity(
            tampered_hmac,
            smoke_script_path=SMOKE_SCRIPT_PATH,
        )


def test_live_evidence_cli_summary_is_redacted_and_digest_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {
        "live": True,
        "status": "ok",
        "source_commit": "a" * 40,
        "completed_at": "2026-08-27T00:00:00+00:00",
        "checks": [
            {"modality": modality}
            for modality in ("text", "image", "video", "audio")
        ],
    }
    evidence_path = tmp_path / "live-evidence.json"
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(verify_live_evidence, "validate_activation_evidence", lambda _: None)

    result = verify_live_evidence.verify(evidence_path)

    assert result["status"] == "ok"
    assert result["modalities"] == ["audio", "image", "text", "video"]
    assert result["secrets_exposed"] is False
    assert result["evidence_sha256"] == hashlib.sha256(evidence_path.read_bytes()).hexdigest()


def test_live_evidence_requires_a_32_character_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(live_evidence.LIVE_EVIDENCE_HMAC_KEY_ENV, "x" * 31)

    with pytest.raises(live_evidence.LiveEvidenceError, match="32 characters"):
        live_evidence.evidence_hmac_sha256({"status": "ok"})


@pytest.mark.asyncio
async def test_provider_smoke_rejects_empty_downloaded_artifact(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b""))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="empty"):
            await provider_smoke._download(
                client,
                "https://assets.example.test/empty",
                tmp_path / "empty.bin",
            )


@pytest.mark.parametrize(
    "placeholder",
    [
        "REPLACE_WITH_A_REAL_LIVE_EVIDENCE_KEY_123456",
        "placeholder-live-evidence-key-123456",
    ],
)
def test_live_evidence_rejects_example_keys(
    monkeypatch: pytest.MonkeyPatch,
    placeholder: str,
) -> None:
    monkeypatch.setenv(live_evidence.LIVE_EVIDENCE_HMAC_KEY_ENV, placeholder)

    with pytest.raises(live_evidence.LiveEvidenceError, match="placeholder"):
        live_evidence.live_evidence_hmac_key()


@pytest.mark.parametrize(
    "git_operation",
    [live_evidence.current_source_commit, live_evidence.source_tree_clean],
)
def test_git_provenance_timeout_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    git_operation: Callable[[Path], object],
) -> None:
    def timeout_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        assert kwargs["timeout"] == 10.0
        raise subprocess.TimeoutExpired(command, 10.0)

    monkeypatch.setattr(live_evidence.subprocess, "run", timeout_run)

    with pytest.raises(live_evidence.LiveEvidenceError):
        git_operation(SMOKE_SCRIPT_PATH)


@pytest.mark.asyncio
async def test_provider_smoke_without_hmac_key_cannot_produce_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-provider-key")
    monkeypatch.delenv(live_evidence.LIVE_EVIDENCE_HMAC_KEY_ENV, raising=False)

    result = await provider_smoke._run_live(skip_video=False)

    assert result["status"] != "ok"
    assert live_evidence.LIVE_EVIDENCE_HMAC_FIELD not in result


@pytest.mark.asyncio
async def test_provider_smoke_success_is_source_bound_and_signed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-provider-key")
    monkeypatch.setenv(live_evidence.LIVE_EVIDENCE_HMAC_KEY_ENV, HMAC_KEY)
    monkeypatch.setattr(
        live_evidence,
        "current_live_evidence_facts",
        lambda _path: _test_source_facts(),
    )
    monkeypatch.setattr(
        provider_smoke,
        "current_live_evidence_facts",
        lambda _path: _test_source_facts(),
    )

    class FakeProvider:
        @classmethod
        def from_env(cls, *, settings: object) -> FakeProvider:
            del settings
            return cls()

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def complete(self, _request: object) -> SimpleNamespace:
            return SimpleNamespace(
                content="你好",
                model="qwen3.5-plus",
                request_id="text-1",
                usage=object(),
            )

        async def generate(self, _request: object) -> SimpleNamespace:
            return SimpleNamespace(
                images=[
                    SimpleNamespace(
                        remote=None,
                        data_base64=base64.b64encode(b"image").decode("ascii"),
                    )
                ],
                model="qwen-image-3.0-pro",
                request_id="image-1",
                usage=object(),
            )

        async def submit_video(self, _request: object) -> str:
            return "task-1"

        async def wait_for_video(self, _task_id: str) -> SimpleNamespace:
            return SimpleNamespace(
                status=provider_smoke.VideoTaskStatus.SUCCEEDED,
                video=SimpleNamespace(url="https://example.test/video.mp4"),
                request_id="video-1",
                usage=object(),
            )

        async def synthesize(self, _request: object) -> SimpleNamespace:
            return SimpleNamespace(
                model="qwen3-tts-flash",
                audio=SimpleNamespace(url="https://example.test/audio.wav"),
                request_id="audio-1",
                usage=object(),
            )

    async def fake_download(_client: object, _url: str, destination: Path) -> int:
        destination.write_bytes(b"artifact")
        return len(b"artifact")

    monkeypatch.setattr(provider_smoke, "DashScopeProvider", FakeProvider)
    monkeypatch.setattr(provider_smoke, "_download", fake_download)

    result = await provider_smoke._run_live(skip_video=False)

    assert result["status"] == "ok"
    assert result["source_commit"] == "a" * 40
    assert result["catalog_manifest_digest"] == manifest_digest()
    assert result["smoke_script_sha256"] == "b" * 64
    assert result["source_tree_clean"] is True
    assert isinstance(result[live_evidence.LIVE_EVIDENCE_HMAC_FIELD], str)
    for check in result["checks"]:
        if check["modality"] == "text":
            assert check["output_chars"] > 0
        else:
            assert check["artifact_bytes"] > 0
    live_evidence.verify_live_evidence_integrity(
        result,
        smoke_script_path=SMOKE_SCRIPT_PATH,
    )
    assert HMAC_KEY not in str(result)


def _voice_rows(*, active: bool, include_voices: bool = True) -> dict[str, tuple[object, ...]]:
    return {
        key: (
            uuid4(),
            uuid4(),
            uuid4(),
            f"stored-{key}" if include_voices else None,
            active,
        )
        for key in provision_demo_voice_resources.VOICE_TARGETS
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("active", "revalidate", "include_voices"),
    [(True, True, True), (False, False, True), (False, False, False)],
)
async def test_voice_provision_requires_confirmation_before_provider_post(
    monkeypatch: pytest.MonkeyPatch,
    active: bool,
    revalidate: bool,
    include_voices: bool,
) -> None:
    rows = _voice_rows(active=active, include_voices=include_voices)

    async def fake_load(_tenant_slug: str) -> tuple[object, dict[str, tuple[object, ...]]]:
        return uuid4(), rows

    monkeypatch.setattr(provision_demo_voice_resources, "_load_tenant_bindings", fake_load)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-provider-key")

    with pytest.raises(RuntimeError, match="confirmation"):
        await provision_demo_voice_resources._provision_locked(
            tenant_slug="mosaic-demo",
            confirm_provider_charges=False,
            revalidate=revalidate,
        )


@pytest.mark.asyncio
async def test_voice_provision_rejects_placeholder_provider_key_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _voice_rows(active=False)

    async def fake_load(_tenant_slug: str) -> tuple[object, dict[str, tuple[object, ...]]]:
        return uuid4(), rows

    monkeypatch.setattr(provision_demo_voice_resources, "_load_tenant_bindings", fake_load)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "REPLACE_WITH_PROVIDER_KEY_FROM_SECRET_INJECTOR")

    with pytest.raises(ProviderConfigurationError):
        await provision_demo_voice_resources._provision_locked(
            tenant_slug="mosaic-demo",
            confirm_provider_charges=True,
            revalidate=False,
        )


@pytest.mark.asyncio
async def test_full_stack_smoke_requires_confirmation_before_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOSAIC_DEMO_EMAIL", raising=False)
    monkeypatch.delenv("MOSAIC_DEMO_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="confirm-provider-charges"):
        await full_stack_live_smoke.run(
            base_url="http://127.0.0.1:8000",
            tenant_slug="mosaic-demo",
            timeout_seconds=10,
        )


def test_full_stack_parser_exposes_explicit_charge_confirmation() -> None:
    args = full_stack_live_smoke._parser().parse_args(["--confirm-provider-charges"])

    assert args.confirm_provider_charges is True
