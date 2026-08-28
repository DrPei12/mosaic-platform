"""Exercise every customer-visible model through the running MOSAIC API.

The smoke logs in with the local demo account, validates that the catalog only
advertises executable models, then runs the real chat and durable generation
paths.  It prints only redacted status evidence: no credentials, provider
resource IDs, signed URLs, response content, or artifact bytes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXPECTED_VISIBLE_MODELS = frozenset(
    {
        "qwen-3-5-plus",
        "qwen-image-3-0-pro",
        "wan-2-7",
        "qwen3-tts-flash",
        "qwen3-tts-voice-design",
        "qwen3-tts-custom-voice",
    }
)
MEDIA_INPUTS: dict[str, tuple[str, dict[str, Any]]] = {
    "qwen-image-3-0-pro": (
        "image",
        {
            "prompt": "极简白色桌面上的蓝色玻璃立方体，柔和自然光，产品摄影",
            "size": "512*512",
            "count": 1,
        },
    ),
    "wan-2-7": (
        "video",
        {
            "prompt": "清晨的湖面上，一只纸船缓慢向前漂动，固定镜头，电影感",
            "resolution": "720P",
            "ratio": "16:9",
            "duration_seconds": 2,
        },
    ),
    "qwen3-tts-flash": (
        "audio",
        {"text": "这是标准语音模型的真实生成测试。", "language_type": "Chinese"},
    ),
    "qwen3-tts-voice-design": (
        "audio",
        {"text": "这是声音设计模型的真实生成测试。", "language_type": "Chinese"},
    ),
    "qwen3-tts-custom-voice": (
        "audio",
        {"text": "这是自定义音色模型的真实生成测试。", "language_type": "Chinese"},
    ),
}
TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "cancelled", "expired"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a real MOSAIC full-stack smoke")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant", default="mosaic-demo")
    parser.add_argument("--timeout-seconds", type=int, default=360)
    parser.add_argument(
        "--confirm-provider-charges",
        action="store_true",
        help="required before login because this smoke submits chargeable work",
    )
    return parser


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} response is not an object")
    return value


async def _json(response: httpx.Response, label: str) -> Mapping[str, Any]:
    if response.status_code >= 400:
        raise RuntimeError(f"{label} failed with HTTP {response.status_code}")
    return _mapping(response.json(), label)


def _csrf_headers(client: httpx.AsyncClient, request_id: str) -> dict[str, str]:
    csrf = client.cookies.get("mosaic_csrf")
    if not csrf:
        raise RuntimeError("login response did not set a CSRF cookie")
    return {
        "X-CSRF-Token": csrf,
        "Idempotency-Key": request_id,
        "Content-Type": "application/json",
    }


async def _login(
    client: httpx.AsyncClient,
    *,
    account: str,
    password: str,
    tenant_slug: str,
) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"account": account, "password": password, "tenant_slug": tenant_slug},
    )
    payload = await _json(response, "login")
    if payload.get("authenticated") is not True:
        raise RuntimeError("login did not create an authenticated session")
    _csrf_headers(client, "login-check")


async def _visible_models(client: httpx.AsyncClient) -> set[str]:
    payload = await _json(await client.get("/api/v1/models"), "catalog")
    items = payload.get("items")
    if not isinstance(items, list):
        raise TypeError("catalog items are invalid")
    visible: set[str] = set()
    for item in items:
        row = _mapping(item, "catalog item")
        model = _mapping(row.get("model"), "catalog model")
        key = model.get("product_model_id")
        if not isinstance(key, str):
            raise TypeError("catalog model ID is invalid")
        if model.get("availability") != "available":
            raise RuntimeError(f"customer-visible model is not executable: {key}")
        visible.add(key)
    if visible != set(EXPECTED_VISIBLE_MODELS):
        raise RuntimeError("customer-visible executable catalog does not match the live gate")
    return visible


async def _chat(client: httpx.AsyncClient) -> dict[str, Any]:
    create_id = str(uuid4())
    conversation = await _json(
        await client.post(
            "/api/v1/conversations",
            headers=_csrf_headers(client, create_id),
            json={
                "product_model_id": "qwen-3-5-plus",
                "client_request_id": create_id,
            },
        ),
        "conversation create",
    )
    conversation_id = conversation.get("conversation_id")
    if not isinstance(conversation_id, str):
        raise TypeError("conversation ID is missing")

    message_id = str(uuid4())
    terminal: Mapping[str, Any] | None = None
    async with client.stream(
        "POST",
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={
            **_csrf_headers(client, message_id),
            "Accept": "text/event-stream",
        },
        json={
            "content": "用一句中文确认：这是一次真实模型调用。",
            "client_request_id": message_id,
        },
    ) as response:
        if response.status_code >= 400:
            raise RuntimeError(f"chat submission failed with HTTP {response.status_code}")
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            event = _mapping(json.loads(line.removeprefix("data:").strip()), "chat event")
            if event.get("type") in {"completed", "failed", "stopped"}:
                terminal = event
                break
    if terminal is None or terminal.get("type") != "completed":
        raise RuntimeError("chat stream did not complete successfully")
    content = terminal.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("chat stream returned no content")
    return {
        "product_model_id": "qwen-3-5-plus",
        "status": "succeeded",
        "output_present": True,
    }


async def _wait_job(
    client: httpx.AsyncClient,
    *,
    job_id: str,
    timeout_seconds: int,
) -> Mapping[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        payload = await _json(
            await client.get(f"/api/v1/generations/{job_id}"),
            "generation status",
        )
        status = payload.get("status")
        if status in TERMINAL_JOB_STATUSES:
            return payload
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError("generation job timed out")
        await asyncio.sleep(1)


async def _generation(
    client: httpx.AsyncClient,
    *,
    model_key: str,
    modality: str,
    input_values: Mapping[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    request_id = str(uuid4())
    accepted = await _json(
        await client.post(
            "/api/v1/generations",
            headers=_csrf_headers(client, request_id),
            json={
                "product_model_id": model_key,
                "modality": modality,
                "input": dict(input_values),
                "client_request_id": request_id,
            },
        ),
        f"{model_key} submission",
    )
    job_id = accepted.get("job_id")
    if not isinstance(job_id, str):
        raise TypeError("generation job ID is missing")
    completed = await _wait_job(
        client,
        job_id=job_id,
        timeout_seconds=timeout_seconds,
    )
    if completed.get("status") != "succeeded":
        code = completed.get("error_code")
        raise RuntimeError(f"{model_key} generation failed ({code or 'unknown'})")
    artifacts = completed.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise RuntimeError(f"{model_key} produced no artifact")
    artifact = _mapping(artifacts[0], "generation artifact")
    artifact_id = artifact.get("artifact_id")
    if not isinstance(artifact_id, str):
        raise TypeError("generation artifact ID is missing")
    download = await client.get(
        f"/api/v1/generations/{job_id}/artifacts/{artifact_id}"
    )
    if download.status_code != 200 or not download.content:
        raise RuntimeError(f"{model_key} artifact download failed")
    return {
        "product_model_id": model_key,
        "status": "succeeded",
        "artifact_count": len(artifacts),
        "artifact_bytes_present": True,
    }


async def run(
    *,
    base_url: str,
    tenant_slug: str,
    timeout_seconds: int,
    confirm_provider_charges: bool = False,
) -> dict[str, Any]:
    if not confirm_provider_charges:
        raise RuntimeError("--confirm-provider-charges is required before live smoke")

    account = os.getenv("MOSAIC_DEMO_EMAIL", "").strip()
    password = os.getenv("MOSAIC_DEMO_PASSWORD", "")
    if not account or not password:
        raise RuntimeError("demo credentials are not configured")
    if timeout_seconds < 10:
        raise ValueError("timeout must be at least 10 seconds")

    checks: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=httpx.Timeout(float(timeout_seconds) + 30),
        follow_redirects=True,
    ) as client:
        await _login(
            client,
            account=account,
            password=password,
            tenant_slug=tenant_slug,
        )
        visible = await _visible_models(client)
        checks.append(await _chat(client))
        for model_key in sorted(visible - {"qwen-3-5-plus"}):
            modality, input_values = MEDIA_INPUTS[model_key]
            checks.append(
                await _generation(
                    client,
                    model_key=model_key,
                    modality=modality,
                    input_values=input_values,
                    timeout_seconds=timeout_seconds,
                )
            )

    return {
        "status": "ok",
        "live": True,
        "catalog_model_count": len(EXPECTED_VISIBLE_MODELS),
        "checks": checks,
        "secrets_exposed": False,
    }


async def _run(args: argparse.Namespace) -> None:
    result = await run(
        base_url=args.base_url,
        tenant_slug=args.tenant,
        timeout_seconds=args.timeout_seconds,
        confirm_provider_charges=args.confirm_provider_charges,
    )
    print(json.dumps(result, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        asyncio.run(_run(args))
    except (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError) as error:
        print(f"full-stack live smoke failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EXPECTED_VISIBLE_MODELS", "MEDIA_INPUTS", "main", "run"]
