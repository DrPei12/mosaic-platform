"""Durable, tenant-scoped artifact storage adapters.

The S3 adapter is the production path.  Its boto3 calls are synchronous, so
every SDK operation is isolated in ``asyncio.to_thread``.  Local storage is
kept for explicit development/test configurations and uses the same
validation and authenticated streaming boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import tempfile
import uuid
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any, BinaryIO, Final, Protocol, cast
from urllib.parse import urlsplit

import httpx
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from app.core.settings import Settings
from app.generations.errors import GenerationInfrastructureError, GenerationNotFoundError
from app.generations.ports import ArtifactStoragePort, StoredArtifact
from app.observability.metrics import record_artifact_failure, record_artifact_transfer
from app.providers.ports import RemoteAsset

_ARTIFACT_ROOT_NAME: Final[str] = "Mosaic/artifacts"
_MAX_ARTIFACT_BYTES: Final[int] = 200 * 1024 * 1024
_STREAM_CHUNK_BYTES: Final[int] = 1024 * 1024
_SPOOL_MEMORY_BYTES: Final[int] = 8 * 1024 * 1024
_MAGIC_PREFIX_BYTES: Final[int] = 32
_KIND_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_KEY_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<kind>[a-z][a-z0-9_-]{0,31})-(?P<nonce>[0-9a-f]{32})(?P<extension>\.[a-z0-9]+)$"
)
_ARTIFACT_KINDS: Final[frozenset[str]] = frozenset(
    {"input", "output", "thumbnail", "preview"}
)
_MIME_EXTENSIONS: Final[dict[str, str]] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "audio/wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
}
SUPPORTED_ARTIFACT_MIME_TYPES: Final[frozenset[str]] = frozenset(_MIME_EXTENSIONS)
DEFAULT_PROVIDER_ALLOWED_HOSTS: Final[tuple[str, ...]] = ("assets.aliyuncs.com",)


class _S3Client(Protocol):
    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def delete_object(self, **kwargs: Any) -> Mapping[str, Any]: ...


class _ReadableBody(Protocol):
    def read(self, amount: int) -> bytes: ...

    def close(self) -> None: ...


def _new_provider_client(*, timeout_seconds: float, trust_env: bool) -> httpx.AsyncClient:
    if timeout_seconds <= 0:
        raise ValueError("provider timeout must be positive")
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=False,
        trust_env=trust_env,
    )


def _normalise_allowed_hosts(values: tuple[str, ...]) -> frozenset[str]:
    if not values:
        raise ValueError("provider allowed hosts must not be empty")
    hosts: set[str] = set()
    for value in values:
        host = value.strip().lower().rstrip(".")
        if not host or "*" in host or "/" in host or ":" in host:
            raise ValueError("provider allowed hosts must contain exact hostnames")
        hosts.add(host)
    return frozenset(hosts)


def _validate_provider_url(value: str, *, allowed_hosts: frozenset[str]) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_URL_INVALID") from exc
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or hostname not in allowed_hosts
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.path
    ):
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_URL_INVALID")
    try:
        return RemoteAsset.from_url(value).url
    except ValueError as exc:
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_URL_INVALID") from exc


async def _remote_chunks(
    *,
    client: httpx.AsyncClient,
    url: str,
    max_bytes: int,
) -> AsyncIterator[bytes]:
    try:
        async with client.stream(
            "GET",
            url,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_DOWNLOAD_FAILED")
            length = response.headers.get("content-length")
            if length is not None and _content_length(length) > max_bytes:
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_TOO_LARGE")
            async for chunk in response.aiter_bytes():
                if not isinstance(chunk, bytes):
                    raise GenerationInfrastructureError("GENERATION_ARTIFACT_DOWNLOAD_FAILED")
                yield chunk
    except GenerationInfrastructureError:
        raise
    except httpx.HTTPError as exc:
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_DOWNLOAD_FAILED") from exc


async def _consume_chunks(
    *,
    chunks: AsyncIterator[bytes],
    handle: BinaryIO,
    mime_type: str,
    max_bytes: int,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    prefix = bytearray()
    total = 0
    async for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise GenerationInfrastructureError("GENERATION_ARTIFACT_DOWNLOAD_FAILED")
        total += len(chunk)
        if total > max_bytes:
            raise GenerationInfrastructureError("GENERATION_ARTIFACT_TOO_LARGE")
        if len(prefix) < _MAGIC_PREFIX_BYTES:
            prefix.extend(chunk[: _MAGIC_PREFIX_BYTES - len(prefix)])
        digest.update(chunk)
        handle.write(chunk)
    if not _magic_matches(mime_type, bytes(prefix)):
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_MIME_MISMATCH")
    return total, digest.hexdigest()


def _magic_matches(mime_type: str, prefix: bytes) -> bool:
    if mime_type == "image/png":
        return prefix.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return prefix.startswith(b"\xff\xd8\xff")
    if mime_type == "image/webp":
        return len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"
    if mime_type == "video/mp4":
        return len(prefix) >= 12 and prefix[4:8] == b"ftyp"
    if mime_type == "audio/wav":
        return len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE"
    if mime_type == "audio/mpeg":
        return prefix.startswith(b"ID3") or (
            len(prefix) >= 2 and prefix[0] == 0xFF and prefix[1] & 0xE0 == 0xE0
        )
    if mime_type == "audio/ogg":
        return prefix.startswith(b"OggS")
    return False


def _validate_mime(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("artifact mime type must be a string")
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_ARTIFACT_MIME_TYPES:
        raise ValueError("unsupported artifact mime type")
    return normalized


def _content_length(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_DOWNLOAD_FAILED") from exc
    if parsed < 0:
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_DOWNLOAD_FAILED")
    return parsed


def _new_key(tenant_id: uuid.UUID, job_id: uuid.UUID, kind: str, mime_type: str) -> str:
    if not isinstance(tenant_id, uuid.UUID) or not isinstance(job_id, uuid.UUID):
        raise TypeError("tenant_id and job_id must be UUIDs")
    if _KIND_RE.fullmatch(kind) is None or kind not in _ARTIFACT_KINDS:
        raise ValueError("invalid artifact kind")
    extension = _MIME_EXTENSIONS[mime_type]
    return f"{tenant_id}/{job_id}/{kind}-{uuid.uuid4().hex}{extension}"


def _validate_scoped_key(*, tenant_id: uuid.UUID, job_id: uuid.UUID, object_key: str) -> str:
    if not isinstance(tenant_id, uuid.UUID) or not isinstance(job_id, uuid.UUID):
        raise TypeError("tenant_id and job_id must be UUIDs")
    expected_prefix = f"{tenant_id}/{job_id}/"
    if not isinstance(object_key, str) or not object_key.startswith(expected_prefix):
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_KEY_INVALID")
    parts = object_key.split("/")
    if len(parts) != 3 or parts[:2] != [str(tenant_id), str(job_id)]:
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_KEY_INVALID")
    match = _KEY_NAME_RE.fullmatch(parts[2])
    if match is None or match.group("kind") not in _ARTIFACT_KINDS:
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_KEY_INVALID")
    if match.group("extension") not in _MIME_EXTENSIONS.values():
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_KEY_INVALID")
    return object_key


async def _file_stream(handle: BinaryIO) -> AsyncIterator[bytes]:
    try:
        while True:
            chunk = await asyncio.to_thread(handle.read, _STREAM_CHUNK_BYTES)
            if not chunk:
                return
            yield chunk
    finally:
        await asyncio.to_thread(handle.close)


async def _s3_body_stream(body: _ReadableBody, *, max_bytes: int) -> AsyncIterator[bytes]:
    total = 0
    try:
        while True:
            chunk = await asyncio.to_thread(body.read, _STREAM_CHUNK_BYTES)
            if not isinstance(chunk, bytes):
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_READ_FAILED")
            if not chunk:
                return
            total += len(chunk)
            if total > max_bytes:
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_TOO_LARGE")
            yield chunk
    finally:
        await asyncio.to_thread(body.close)


async def _observed_stream(
    chunks: AsyncIterator[bytes],
    *,
    direction: str,
    operation: str,
) -> AsyncIterator[bytes]:
    total = 0
    try:
        async for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_READ_FAILED")
            total += len(chunk)
            yield chunk
    except Exception:
        record_artifact_failure(direction=direction, operation=operation)
        raise
    else:
        record_artifact_transfer(direction=direction, byte_count=total)


class LocalArtifactStorage(ArtifactStoragePort):
    """Explicit development/test storage beneath ``LOCALAPPDATA``."""

    storage_provider = "local_fs"

    def __init__(
        self,
        *,
        root: str | os.PathLike[str] | None = None,
        client: httpx.AsyncClient | None = None,
        max_bytes: int = _MAX_ARTIFACT_BYTES,
        provider_allowed_hosts: tuple[str, ...] = DEFAULT_PROVIDER_ALLOWED_HOSTS,
        provider_timeout_seconds: float = 120.0,
        provider_trust_env: bool = False,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self._root = self._resolve_root(root)
        self._client = client
        self._max_bytes = max_bytes
        self._provider_allowed_hosts = _normalise_allowed_hosts(provider_allowed_hosts)
        self._provider_timeout_seconds = provider_timeout_seconds
        self._provider_trust_env = provider_trust_env

    @staticmethod
    def _resolve_root(root: str | os.PathLike[str] | None) -> Path:
        if root is None:
            local_app_data = os.environ.get("LOCALAPPDATA")
            if not local_app_data:
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_ROOT_UNAVAILABLE")
            root = Path(local_app_data) / _ARTIFACT_ROOT_NAME
        return Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        return self._root

    async def transfer_remote(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        remote_url: str,
        kind: str,
        mime_type: str,
    ) -> StoredArtifact:
        try:
            expected_mime = _validate_mime(mime_type)
            url = _validate_provider_url(remote_url, allowed_hosts=self._provider_allowed_hosts)
            target_key = _new_key(tenant_id, job_id, kind, expected_mime)
            target = self.resolve_object_path(target_key)
            client = self._client or _new_provider_client(
                timeout_seconds=self._provider_timeout_seconds,
                trust_env=self._provider_trust_env,
            )
            owns_client = self._client is None
            try:
                result = await self._write_stream(
                    target_key=target_key,
                    target=target,
                    chunks=_remote_chunks(client=client, url=url, max_bytes=self._max_bytes),
                    mime_type=expected_mime,
                )
            finally:
                if owns_client:
                    await client.aclose()
            record_artifact_transfer(direction="write", byte_count=result.size_bytes)
            return result
        except Exception:
            record_artifact_failure(direction="write", operation="transfer_remote")
            raise

    async def open_stream(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        object_key: str,
    ) -> AsyncIterator[bytes]:
        try:
            scoped_key = _validate_scoped_key(
                tenant_id=tenant_id,
                job_id=job_id,
                object_key=object_key,
            )
            path = self.resolve_object_path(scoped_key)
            if not path.is_file():
                raise GenerationNotFoundError()
            try:
                handle = path.open("rb")
            except FileNotFoundError as exc:
                raise GenerationNotFoundError() from exc
            except OSError as exc:
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_READ_FAILED") from exc
        except Exception:
            record_artifact_failure(direction="read", operation="open_stream")
            raise
        return _observed_stream(
            _file_stream(handle),
            direction="read",
            operation="open_stream",
        )

    async def put_bytes(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        content: bytes,
        kind: str,
        mime_type: str,
    ) -> StoredArtifact:
        try:
            if not isinstance(content, bytes):
                raise TypeError("artifact content must be bytes")
            expected_mime = _validate_mime(mime_type)
            if len(content) > self._max_bytes:
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_TOO_LARGE")
            if not _magic_matches(expected_mime, content[:_MAGIC_PREFIX_BYTES]):
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_MIME_MISMATCH")
            target_key = _new_key(tenant_id, job_id, kind, expected_mime)
            target = self.resolve_object_path(target_key)
            result = await self._write_stream(
                target_key=target_key,
                target=target,
                chunks=_one_chunk(content),
                mime_type=expected_mime,
            )
            record_artifact_transfer(direction="write", byte_count=result.size_bytes)
            return result
        except Exception:
            record_artifact_failure(direction="write", operation="put_bytes")
            raise

    async def delete_object(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        object_key: str,
    ) -> None:
        scoped_key = _validate_scoped_key(
            tenant_id=tenant_id,
            job_id=job_id,
            object_key=object_key,
        )
        path = self.resolve_object_path(scoped_key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as exc:
            raise GenerationInfrastructureError("GENERATION_ARTIFACT_DELETE_FAILED") from exc

    def resolve_object_path(self, object_key: str) -> Path:
        """Resolve a local key only if it remains beneath the artifact root."""

        if not isinstance(object_key, str) or not object_key.strip():
            raise GenerationInfrastructureError("GENERATION_ARTIFACT_KEY_INVALID")
        key_path = Path(object_key)
        if key_path.is_absolute() or ".." in key_path.parts:
            raise GenerationInfrastructureError("GENERATION_ARTIFACT_KEY_INVALID")
        candidate = (self._root / key_path).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise GenerationInfrastructureError("GENERATION_ARTIFACT_KEY_INVALID") from exc
        return candidate

    @staticmethod
    def _new_key(
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        kind: str,
        mime_type: str,
    ) -> str:
        return _new_key(tenant_id, job_id, kind, mime_type)

    async def _write_stream(
        self,
        *,
        target_key: str,
        target: Path,
        chunks: AsyncIterator[bytes],
        mime_type: str,
    ) -> StoredArtifact:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        try:
            with temporary.open("wb") as handle:
                total, digest = await _consume_chunks(
                    chunks=chunks,
                    handle=handle,
                    mime_type=mime_type,
                    max_bytes=self._max_bytes,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except GenerationInfrastructureError:
            _unlink_quietly(temporary)
            raise
        except OSError as exc:
            _unlink_quietly(temporary)
            raise GenerationInfrastructureError("GENERATION_ARTIFACT_WRITE_FAILED") from exc
        return StoredArtifact(
            storage_provider=self.storage_provider,
            object_key=target_key,
            mime_type=mime_type,
            size_bytes=total,
            sha256=digest,
        )


class S3ArtifactStorage(ArtifactStoragePort):
    """S3-compatible storage using boto3 behind an async-safe boundary."""

    storage_provider = "s3"

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        region: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        max_bytes: int = _MAX_ARTIFACT_BYTES,
        s3_timeout_seconds: float = 60.0,
        provider_allowed_hosts: tuple[str, ...] = DEFAULT_PROVIDER_ALLOWED_HOSTS,
        provider_timeout_seconds: float = 120.0,
        provider_trust_env: bool = False,
        client: _S3Client | None = None,
        provider_client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if s3_timeout_seconds <= 0:
            raise ValueError("s3 timeout must be positive")
        if not endpoint_url.strip() or not bucket.strip() or not region.strip():
            raise ValueError("S3 endpoint, bucket and region are required")
        if bool(access_key_id) != bool(secret_access_key):
            raise ValueError("S3 credentials must be supplied as a pair")
        self._endpoint_url = endpoint_url.rstrip("/")
        self._bucket = bucket
        self._max_bytes = max_bytes
        self._provider_allowed_hosts = _normalise_allowed_hosts(provider_allowed_hosts)
        self._provider_timeout_seconds = provider_timeout_seconds
        self._provider_trust_env = provider_trust_env
        self._provider_client = provider_client
        self._s3_client = client or _build_s3_client(
            endpoint_url=self._endpoint_url,
            region=region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            timeout_seconds=s3_timeout_seconds,
        )

    async def transfer_remote(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        remote_url: str,
        kind: str,
        mime_type: str,
    ) -> StoredArtifact:
        try:
            expected_mime = _validate_mime(mime_type)
            url = _validate_provider_url(remote_url, allowed_hosts=self._provider_allowed_hosts)
            target_key = _new_key(tenant_id, job_id, kind, expected_mime)
            client = self._provider_client or _new_provider_client(
                timeout_seconds=self._provider_timeout_seconds,
                trust_env=self._provider_trust_env,
            )
            owns_client = self._provider_client is None
            with tempfile.SpooledTemporaryFile(max_size=_SPOOL_MEMORY_BYTES, mode="w+b") as spool:
                try:
                    total, digest = await _consume_chunks(
                        chunks=_remote_chunks(client=client, url=url, max_bytes=self._max_bytes),
                        handle=cast(BinaryIO, spool),
                        mime_type=expected_mime,
                        max_bytes=self._max_bytes,
                    )
                    spool.seek(0)
                    try:
                        await asyncio.to_thread(
                            self._put_file_object,
                            target_key,
                            cast(BinaryIO, spool),
                            expected_mime,
                            total,
                            digest,
                        )
                    except (BotoCoreError, ClientError, OSError) as exc:
                        raise GenerationInfrastructureError(
                            "GENERATION_ARTIFACT_WRITE_FAILED"
                        ) from exc
                    result = StoredArtifact(
                        storage_provider=self.storage_provider,
                        object_key=target_key,
                        mime_type=expected_mime,
                        size_bytes=total,
                        sha256=digest,
                    )
                finally:
                    if owns_client:
                        await client.aclose()
            record_artifact_transfer(direction="write", byte_count=result.size_bytes)
            return result
        except Exception:
            record_artifact_failure(direction="write", operation="transfer_remote")
            raise

    async def open_stream(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        object_key: str,
    ) -> AsyncIterator[bytes]:
        try:
            scoped_key = _validate_scoped_key(
                tenant_id=tenant_id,
                job_id=job_id,
                object_key=object_key,
            )
            try:
                result = await asyncio.to_thread(
                    self._s3_client.get_object,
                    Bucket=self._bucket,
                    Key=scoped_key,
                )
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in {"404", "NoSuchKey"}:
                    raise GenerationNotFoundError() from exc
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_READ_FAILED") from exc
            except (BotoCoreError, OSError) as exc:
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_READ_FAILED") from exc
            body = result.get("Body")
            if body is None:
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_READ_FAILED")
            content_length = result.get("ContentLength")
            if content_length is not None and int(content_length) > self._max_bytes:
                cast(_ReadableBody, body).close()
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_TOO_LARGE")
        except Exception:
            record_artifact_failure(direction="read", operation="open_stream")
            raise
        return _observed_stream(
            _s3_body_stream(cast(_ReadableBody, body), max_bytes=self._max_bytes),
            direction="read",
            operation="open_stream",
        )

    async def put_bytes(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        content: bytes,
        kind: str,
        mime_type: str,
    ) -> StoredArtifact:
        try:
            if not isinstance(content, bytes):
                raise TypeError("artifact content must be bytes")
            expected_mime = _validate_mime(mime_type)
            if len(content) > self._max_bytes:
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_TOO_LARGE")
            if not _magic_matches(expected_mime, content[:_MAGIC_PREFIX_BYTES]):
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_MIME_MISMATCH")
            target_key = _new_key(tenant_id, job_id, kind, expected_mime)
            digest = hashlib.sha256(content).hexdigest()
            try:
                await asyncio.to_thread(
                    self._s3_client.put_object,
                    Bucket=self._bucket,
                    Key=target_key,
                    Body=content,
                    ContentLength=len(content),
                    ContentType=expected_mime,
                    Metadata={"sha256": digest},
                )
            except (BotoCoreError, ClientError, OSError) as exc:
                raise GenerationInfrastructureError("GENERATION_ARTIFACT_WRITE_FAILED") from exc
            result = StoredArtifact(
                storage_provider=self.storage_provider,
                object_key=target_key,
                mime_type=expected_mime,
                size_bytes=len(content),
                sha256=digest,
            )
            record_artifact_transfer(direction="write", byte_count=result.size_bytes)
            return result
        except Exception:
            record_artifact_failure(direction="write", operation="put_bytes")
            raise

    async def delete_object(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        object_key: str,
    ) -> None:
        scoped_key = _validate_scoped_key(
            tenant_id=tenant_id,
            job_id=job_id,
            object_key=object_key,
        )
        try:
            await asyncio.to_thread(
                self._s3_client.delete_object,
                Bucket=self._bucket,
                Key=scoped_key,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise GenerationInfrastructureError("GENERATION_ARTIFACT_DELETE_FAILED") from exc

    def _put_file_object(
        self,
        object_key: str,
        body: BinaryIO,
        mime_type: str,
        size_bytes: int,
        digest: str,
    ) -> None:
        self._s3_client.put_object(
            Bucket=self._bucket,
            Key=object_key,
            Body=body,
            ContentLength=size_bytes,
            ContentType=mime_type,
            Metadata={"sha256": digest},
        )


def _build_s3_client(
    *,
    endpoint_url: str,
    region: str,
    access_key_id: str | None,
    secret_access_key: str | None,
    timeout_seconds: float,
) -> _S3Client:
    # boto3/botocore are intentionally kept behind this small construction
    # seam.  The SDK remains synchronous; all later calls use to_thread.
    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config  # type: ignore[import-untyped]

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        config=Config(
            signature_version="s3v4",
            connect_timeout=max(1, int(timeout_seconds)),
            read_timeout=max(1, int(timeout_seconds)),
            retries={"max_attempts": 3, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )
    return cast(_S3Client, client)


def build_artifact_storage(config: Settings) -> ArtifactStoragePort:
    """Build the configured adapter, failing closed on unsafe combinations."""

    if config.artifact_storage_backend == "local":
        if config.app_environment not in {"development", "test"}:
            raise GenerationInfrastructureError("GENERATION_ARTIFACT_STORAGE_NOT_CONFIGURED")
        return LocalArtifactStorage(
            max_bytes=config.artifact_storage_max_bytes,
            provider_allowed_hosts=config.artifact_storage_provider_allowed_hosts,
            provider_timeout_seconds=config.artifact_storage_provider_timeout_seconds,
            provider_trust_env=config.artifact_storage_provider_trust_env,
        )

    endpoint_url = config.artifact_storage_s3_endpoint_url
    bucket = config.artifact_storage_s3_bucket
    if not endpoint_url or not bucket:
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_STORAGE_NOT_CONFIGURED")
    access_key_id = (
        config.artifact_storage_s3_access_key_id.get_secret_value()
        if config.artifact_storage_s3_access_key_id
        else None
    )
    secret_access_key = (
        config.artifact_storage_s3_secret_access_key.get_secret_value()
        if config.artifact_storage_s3_secret_access_key
        else None
    )
    if bool(access_key_id) != bool(secret_access_key):
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_STORAGE_NOT_CONFIGURED")
    try:
        return S3ArtifactStorage(
            endpoint_url=endpoint_url,
            bucket=bucket,
            region=config.artifact_storage_s3_region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            max_bytes=config.artifact_storage_max_bytes,
            s3_timeout_seconds=config.artifact_storage_s3_timeout_seconds,
            provider_allowed_hosts=config.artifact_storage_provider_allowed_hosts,
            provider_timeout_seconds=config.artifact_storage_provider_timeout_seconds,
            provider_trust_env=config.artifact_storage_provider_trust_env,
        )
    except ValueError as exc:
        raise GenerationInfrastructureError("GENERATION_ARTIFACT_STORAGE_NOT_CONFIGURED") from exc


async def _one_chunk(content: bytes) -> AsyncIterator[bytes]:
    yield content


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


__all__ = [
    "DEFAULT_PROVIDER_ALLOWED_HOSTS",
    "SUPPORTED_ARTIFACT_MIME_TYPES",
    "LocalArtifactStorage",
    "S3ArtifactStorage",
    "build_artifact_storage",
]
