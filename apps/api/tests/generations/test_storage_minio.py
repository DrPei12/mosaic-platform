from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.generations.storage import S3ArtifactStorage


@pytest.mark.minio
@pytest.mark.asyncio
async def test_minio_round_trip_when_explicitly_enabled() -> None:
    if os.environ.get("RUN_MINIO_INTEGRATION") != "1":
        pytest.skip("set RUN_MINIO_INTEGRATION=1 to run the local MinIO integration")

    storage = S3ArtifactStorage(
        endpoint_url=os.environ.get("ARTIFACT_STORAGE_S3_ENDPOINT_URL", "http://127.0.0.1:9000"),
        bucket=os.environ.get("ARTIFACT_STORAGE_S3_BUCKET", "mosaic-artifacts"),
        region=os.environ.get("ARTIFACT_STORAGE_S3_REGION", "us-east-1"),
        access_key_id=os.environ.get("ARTIFACT_STORAGE_S3_ACCESS_KEY_ID", "minioadmin"),
        secret_access_key=os.environ.get(
            "ARTIFACT_STORAGE_S3_SECRET_ACCESS_KEY",
            "minioadmin",
        ),
    )
    content = b"\x89PNG\r\n\x1a\nminio-integration"
    tenant_id = uuid4()
    job_id = uuid4()
    stored = await storage.put_bytes(
        tenant_id=tenant_id,
        job_id=job_id,
        content=content,
        kind="output",
        mime_type="image/png",
    )
    stream = await storage.open_stream(
        tenant_id=tenant_id,
        job_id=job_id,
        object_key=stored.object_key,
    )
    assert b"".join([chunk async for chunk in stream]) == content
