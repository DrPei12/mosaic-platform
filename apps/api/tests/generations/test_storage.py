from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.core.settings import Settings
from app.generations.errors import GenerationInfrastructureError
from app.generations.storage import (
    LocalArtifactStorage,
    S3ArtifactStorage,
    build_artifact_storage,
)

PNG = b"\x89PNG\r\n\x1a\nunit-test-png"
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00unit-test-mp4"


class _Body:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self._offset = 0
        self.closed = False

    def read(self, amount: int) -> bytes:
        chunk = self._content[self._offset : self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class _S3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.call_threads: list[int] = []

    def put_object(self, **kwargs: object) -> dict[str, object]:
        self.call_threads.append(threading.get_ident())
        body = kwargs["Body"]
        if isinstance(body, bytes):
            content = body
        else:
            file_body = body
            assert hasattr(file_body, "read")
            content = file_body.read()  # type: ignore[union-attr]
        assert isinstance(content, bytes)
        object_key = kwargs["Key"]
        assert isinstance(object_key, str)
        self.objects[object_key] = content
        self.put_calls.append(kwargs)
        return {}

    def get_object(self, **kwargs: object) -> dict[str, object]:
        self.call_threads.append(threading.get_ident())
        self.get_calls.append(kwargs)
        object_key = kwargs["Key"]
        assert isinstance(object_key, str)
        content = self.objects[object_key]
        return {"Body": _Body(content), "ContentLength": len(content)}

    def delete_object(self, **kwargs: object) -> dict[str, object]:
        self.call_threads.append(threading.get_ident())
        self.delete_calls.append(kwargs)
        object_key = kwargs["Key"]
        assert isinstance(object_key, str)
        self.objects.pop(object_key, None)
        return {}


def _storage(client: _S3Client, **kwargs: object) -> S3ArtifactStorage:
    return S3ArtifactStorage(
        endpoint_url="http://127.0.0.1:9000",
        bucket="mosaic-artifacts",
        client=client,
        **kwargs,
    )


def test_storage_factory_fails_closed_without_s3_configuration() -> None:
    with pytest.raises(GenerationInfrastructureError) as error:
        build_artifact_storage(
            Settings(
                _env_file=None,
                artifact_storage_backend="s3",
                artifact_storage_s3_endpoint_url=None,
                artifact_storage_s3_bucket=None,
            )
        )
    assert error.value.code == "GENERATION_ARTIFACT_STORAGE_NOT_CONFIGURED"


def test_storage_factory_requires_explicit_local_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config = Settings(_env_file=None, app_environment="test", artifact_storage_backend="local")
    storage = build_artifact_storage(config)
    assert isinstance(storage, LocalArtifactStorage)


@pytest.mark.asyncio
async def test_s3_put_and_stream_are_tenant_scoped_and_sdk_calls_leave_event_loop() -> None:
    client = _S3Client()
    storage = _storage(client)
    tenant_id = uuid4()
    job_id = uuid4()
    event_loop_thread = threading.get_ident()

    stored = await storage.put_bytes(
        tenant_id=tenant_id,
        job_id=job_id,
        content=PNG,
        kind="output",
        mime_type="image/png",
    )

    assert stored.object_key.startswith(f"{tenant_id}/{job_id}/output-")
    assert stored.object_key.endswith(".png")
    assert stored.sha256 == hashlib.sha256(PNG).hexdigest()
    assert client.put_calls[0]["Metadata"] == {"sha256": stored.sha256}
    assert client.call_threads[0] != event_loop_thread

    stream = await storage.open_stream(
        tenant_id=tenant_id,
        job_id=job_id,
        object_key=stored.object_key,
    )
    assert b"".join([chunk async for chunk in stream]) == PNG
    assert client.get_calls[0]["Key"] == stored.object_key
    assert client.call_threads[-1] != event_loop_thread

    with pytest.raises(GenerationInfrastructureError) as error:
        await storage.open_stream(
            tenant_id=uuid4(),
            job_id=job_id,
            object_key=stored.object_key,
        )
    assert error.value.code == "GENERATION_ARTIFACT_KEY_INVALID"

    await storage.delete_object(
        tenant_id=tenant_id,
        job_id=job_id,
        object_key=stored.object_key,
    )
    assert stored.object_key not in client.objects
    assert client.delete_calls[0]["Key"] == stored.object_key
    assert client.call_threads[-1] != event_loop_thread


@pytest.mark.asyncio
async def test_local_delete_is_idempotent_and_tenant_scoped(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(root=tmp_path)
    tenant_id = uuid4()
    job_id = uuid4()
    stored = await storage.put_bytes(
        tenant_id=tenant_id,
        job_id=job_id,
        content=PNG,
        kind="output",
        mime_type="image/png",
    )

    await storage.delete_object(
        tenant_id=tenant_id,
        job_id=job_id,
        object_key=stored.object_key,
    )
    await storage.delete_object(
        tenant_id=tenant_id,
        job_id=job_id,
        object_key=stored.object_key,
    )

    assert not storage.resolve_object_path(stored.object_key).exists()
    with pytest.raises(GenerationInfrastructureError):
        await storage.delete_object(
            tenant_id=uuid4(),
            job_id=job_id,
            object_key=stored.object_key,
        )


@pytest.mark.asyncio
async def test_s3_transfer_rejects_redirects_and_uses_exact_https_provider_host() -> None:
    client = _S3Client()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "assets.aliyuncs.com"
        return httpx.Response(302, headers={"location": "https://attacker.example/x"}, request=request)

    provider_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = _storage(client, provider_client=provider_client)
    try:
        with pytest.raises(GenerationInfrastructureError) as redirect_error:
            await storage.transfer_remote(
                tenant_id=uuid4(),
                job_id=uuid4(),
                remote_url="https://assets.aliyuncs.com/output.mp4?signature=secret",
                kind="output",
                mime_type="video/mp4",
            )
        assert redirect_error.value.code == "GENERATION_ARTIFACT_DOWNLOAD_FAILED"

        with pytest.raises(GenerationInfrastructureError) as http_error:
            await storage.transfer_remote(
                tenant_id=uuid4(),
                job_id=uuid4(),
                remote_url="http://assets.aliyuncs.com/output.mp4?signature=secret",
                kind="output",
                mime_type="video/mp4",
            )
        assert http_error.value.code == "GENERATION_ARTIFACT_URL_INVALID"

        with pytest.raises(GenerationInfrastructureError) as host_error:
            await storage.transfer_remote(
                tenant_id=uuid4(),
                job_id=uuid4(),
                remote_url="https://cdn.aliyuncs.com/output.mp4?signature=secret",
                kind="output",
                mime_type="video/mp4",
            )
        assert host_error.value.code == "GENERATION_ARTIFACT_URL_INVALID"
    finally:
        await provider_client.aclose()


@pytest.mark.asyncio
async def test_s3_transfer_downloads_valid_media_and_preserves_checksum() -> None:
    client = _S3Client()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        return httpx.Response(200, content=MP4, request=request)

    provider_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = _storage(client, provider_client=provider_client)
    try:
        stored = await storage.transfer_remote(
            tenant_id=uuid4(),
            job_id=uuid4(),
            remote_url="https://assets.aliyuncs.com/output.mp4?signature=secret",
            kind="output",
            mime_type="video/mp4",
        )
    finally:
        await provider_client.aclose()

    assert stored.size_bytes == len(MP4)
    assert stored.sha256 == hashlib.sha256(MP4).hexdigest()
    assert client.objects[stored.object_key] == MP4


@pytest.mark.asyncio
async def test_storage_rejects_mime_mismatch_and_max_bytes(tmp_path: Path) -> None:
    local = LocalArtifactStorage(root=tmp_path, max_bytes=len(PNG))

    with pytest.raises(GenerationInfrastructureError) as mismatch:
        await local.put_bytes(
            tenant_id=uuid4(),
            job_id=uuid4(),
            content=b"not-a-png",
            kind="output",
            mime_type="image/png",
        )
    assert mismatch.value.code == "GENERATION_ARTIFACT_MIME_MISMATCH"

    with pytest.raises(GenerationInfrastructureError) as too_large:
        await local.put_bytes(
            tenant_id=uuid4(),
            job_id=uuid4(),
            content=PNG + b"too-large",
            kind="output",
            mime_type="image/png",
        )
    assert too_large.value.code == "GENERATION_ARTIFACT_TOO_LARGE"
