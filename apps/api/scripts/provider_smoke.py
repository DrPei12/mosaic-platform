"""Run opt-in live DashScope smoke checks for all supported modalities.

This command intentionally never substitutes a fake provider.  Without
``--live`` or a process credential it reports ``skipped`` and exits non-zero,
so CI cannot mistake a missing live gate for a passing integration test.

Generated media is downloaded into the system temporary directory.  The JSON
summary contains no provider URLs, response bodies, or credentials.  A
successful live result is emitted only from a clean Git tree and is bound to
the current source commit, catalog manifest, smoke-script digest, and an
HMAC key supplied through ``MOSAIC_LIVE_EVIDENCE_HMAC_KEY``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

# Support both ``python scripts/provider_smoke.py`` and module execution from
# the API package root without requiring a project installation first.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.catalog.live_evidence import (
    LiveEvidenceError,
    bind_live_evidence,
    current_live_evidence_facts,
    live_evidence_hmac_key,
)
from app.providers.config import ProviderSettings
from app.providers.dashscope import DashScopeProvider
from app.providers.errors import ProviderError
from app.providers.ports import (
    AudioGenerationRequest,
    ChatMessage,
    ImageGenerationRequest,
    TextCompletionRequest,
    VideoGenerationRequest,
    VideoTaskStatus,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run live DashScope provider smoke checks")
    parser.add_argument(
        "--live",
        action="store_true",
        help="make real provider calls; without this flag the gate is explicitly skipped",
    )
    parser.add_argument(
        "--skip-video",
        action="store_true",
        help="skip the chargeable asynchronous video smoke (still reports skipped)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write the redacted JSON evidence atomically to this local path",
    )
    return parser


def _emit(result: dict[str, Any], output: Path | None) -> None:
    serialized = json.dumps(result, ensure_ascii=False)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(f"{output.suffix}.tmp")
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(output)
    print(serialized)


def _provider_error(error: ProviderError) -> dict[str, Any]:
    public = error.public_dict()
    return {
        "code": public["code"],
        "status_code": public["status_code"],
        "retryable": public["retryable"],
        "request_id_present": public["request_id"] is not None,
    }


async def _download(client: httpx.AsyncClient, url: str, destination: Path) -> int:
    response = await client.get(url)
    response.raise_for_status()
    content = response.content
    if not content:
        raise ValueError("provider artifact is empty")
    destination.write_bytes(content)
    return len(content)


async def _run_live(skip_video: bool) -> dict[str, Any]:
    run_id = str(uuid4())
    started_at = datetime.now(UTC)
    settings = ProviderSettings()
    if (
        settings.dashscope_api_key is None
        or not settings.dashscope_api_key.get_secret_value().strip()
    ):
        return {
            "status": "skipped",
            "reason": "DASHSCOPE_API_KEY is not available in the process environment",
            "live": True,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
        }

    try:
        hmac_key = live_evidence_hmac_key()
        # Do this before any chargeable call.  A live run that cannot be
        # securely bound to the source can never be accepted for activation.
        current_live_evidence_facts(Path(__file__))
    except LiveEvidenceError as error:
        return {
            "status": "failed",
            "reason": str(error),
            "live": True,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
        }

    artifact_dir = Path(tempfile.mkdtemp(prefix="mosaic-bailian-smoke-"))
    checks: list[dict[str, Any]] = []
    async with (
        DashScopeProvider.from_env(settings=settings) as provider,
        httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as downloader,
    ):
        try:
            text_result = await provider.complete(
                TextCompletionRequest(
                    model="qwen3.5-plus",
                    messages=(ChatMessage(role="user", content="用一句话回答：你好"),),
                    max_completion_tokens=32,
                )
            )
            if not text_result.content.strip():
                raise ValueError("provider text output is empty")
            (artifact_dir / "text.txt").write_text(text_result.content, encoding="utf-8")
            checks.append(
                {
                    "modality": "text",
                    "status": "ok",
                    "model_requested": "qwen3.5-plus",
                    "model_reported": text_result.model,
                    "output_chars": len(text_result.content),
                    "request_id_present": bool(text_result.request_id),
                    "usage_present": text_result.usage is not None,
                }
            )
        except ProviderError as error:
            checks.append({"modality": "text", "status": "failed", **_provider_error(error)})
        except ValueError:
            checks.append({"modality": "text", "status": "failed", "code": "text_output_empty"})

        try:
            image_result = await provider.generate(
                ImageGenerationRequest(
                    model="qwen-image-3.0-pro",
                    prompt="一只红色风筝在晴朗的蓝天中，简洁插画风格",
                    size="512*512",
                    count=1,
                )
            )
            downloaded = 0
            downloaded_bytes = 0
            for index, image in enumerate(image_result.images):
                destination = artifact_dir / f"image-{index + 1}.png"
                if image.remote is not None:
                    downloaded_bytes += await _download(
                        downloader,
                        image.remote.url,
                        destination,
                    )
                elif image.data_base64:
                    content = base64.b64decode(image.data_base64, validate=True)
                    if not content:
                        raise ValueError("provider image artifact is empty")
                    destination.write_bytes(content)
                    downloaded_bytes += len(content)
                else:
                    raise ValueError("provider image artifact is missing")
                downloaded += 1
            if downloaded == 0 or downloaded_bytes == 0:
                raise ValueError("provider image output is empty")
            checks.append(
                {
                    "modality": "image",
                    "status": "ok",
                    "model_requested": image_result.model,
                    "model_reported": None,
                    "artifacts": downloaded,
                    "artifact_bytes": downloaded_bytes,
                    "request_id_present": bool(image_result.request_id),
                    "usage_present": image_result.usage is not None,
                }
            )
        except ProviderError as error:
            checks.append({"modality": "image", "status": "failed", **_provider_error(error)})
        except (httpx.HTTPError, ValueError):
            checks.append(
                {
                    "modality": "image",
                    "status": "failed",
                    "code": "artifact_download_or_decode_failed",
                }
            )

        if skip_video:
            checks.append(
                {
                    "modality": "video",
                    "status": "skipped",
                    "reason": "--skip-video was supplied",
                }
            )
        else:
            try:
                task_id = await provider.submit_video(
                    VideoGenerationRequest(
                        model="wan2.7-t2v",
                        prompt="一只红色风筝在湖边的蓝天下缓慢飞过，电影感镜头",
                        resolution="720P",
                        ratio="16:9",
                        duration_seconds=2,
                    )
                )
                video_result = await provider.wait_for_video(task_id)
                if (
                    video_result.status is not VideoTaskStatus.SUCCEEDED
                    or video_result.video is None
                ):
                    checks.append(
                        {
                            "modality": "video",
                            "status": "failed",
                            "code": f"video_task_{video_result.status.value.lower()}",
                        }
                    )
                else:
                    artifact_bytes = await _download(
                        downloader,
                        video_result.video.url,
                        artifact_dir / "video.mp4",
                    )
                    checks.append(
                        {
                            "modality": "video",
                            "status": "ok",
                            "model_requested": "wan2.7-t2v",
                            "model_reported": None,
                            "artifacts": 1,
                            "artifact_bytes": artifact_bytes,
                            "request_id_present": bool(video_result.request_id),
                            "usage_present": video_result.usage is not None,
                        }
                    )
            except ProviderError as error:
                checks.append({"modality": "video", "status": "failed", **_provider_error(error)})
            except (httpx.HTTPError, ValueError):
                checks.append(
                    {
                        "modality": "video",
                        "status": "failed",
                        "code": "video_generation_or_download_failed",
                    }
                )

        try:
            audio_result = await provider.synthesize(
                AudioGenerationRequest(
                    model="qwen3-tts-flash",
                    text="你好，这是一次真实的语音合成连通性测试。",
                    voice="Cherry",
                    language_type="Chinese",
                )
            )
            artifact_bytes = await _download(
                downloader,
                audio_result.audio.url,
                artifact_dir / "audio.wav",
            )
            checks.append(
                {
                    "modality": "audio",
                    "status": "ok",
                    "model_requested": audio_result.model,
                    "model_reported": None,
                    "artifacts": 1,
                    "artifact_bytes": artifact_bytes,
                    "request_id_present": bool(audio_result.request_id),
                    "usage_present": audio_result.usage is not None,
                }
            )
        except ProviderError as error:
            checks.append({"modality": "audio", "status": "failed", **_provider_error(error)})
        except (httpx.HTTPError, ValueError):
            checks.append(
                {
                    "modality": "audio",
                    "status": "failed",
                    "code": "audio_generation_or_download_failed",
                }
            )

    failed = any(check["status"] == "failed" for check in checks)
    skipped = any(check["status"] == "skipped" for check in checks)
    result = {
        "status": "failed" if failed else "ok" if not skipped else "partial",
        "live": True,
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "artifact_dir": str(artifact_dir),
        "checks": checks,
    }
    try:
        return bind_live_evidence(
            result,
            smoke_script_path=Path(__file__),
            key=hmac_key,
        )
    except LiveEvidenceError as error:
        return {**result, "status": "failed", "reason": str(error)}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.live:
        now = datetime.now(UTC).isoformat()
        _emit(
            {
                "status": "skipped",
                "reason": "--live flag is required",
                "live": False,
                "run_id": str(uuid4()),
                "started_at": now,
                "completed_at": now,
            },
            args.output,
        )
        return 2
    result = asyncio.run(_run_live(args.skip_video))
    _emit(result, args.output)
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
