"""Create and verify the configured S3-compatible artifact bucket.

This job deliberately reads only storage settings and does not import the API
Settings object, so a staging drill can use the bundled HTTP MinIO
endpoint while the production API keeps its strict HTTPS validation.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

_BUCKET_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{1,61}[a-z0-9])?")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _endpoint(value: str) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ARTIFACT_STORAGE_S3_ENDPOINT_URL must be a bare HTTP(S) endpoint")
    return parsed._replace(path="", query="", fragment="").geturl().rstrip("/")


def _bucket(value: str) -> str:
    normalized = value.lower()
    if _BUCKET_PATTERN.fullmatch(normalized) is None:
        raise ValueError("ARTIFACT_STORAGE_S3_BUCKET is invalid")
    return normalized


def _ensure_bucket() -> dict[str, object]:
    endpoint = _endpoint(_required("ARTIFACT_STORAGE_S3_ENDPOINT_URL"))
    bucket = _bucket(_required("ARTIFACT_STORAGE_S3_BUCKET"))
    region = _required("ARTIFACT_STORAGE_S3_REGION")
    access_key = _required("ARTIFACT_STORAGE_S3_ACCESS_KEY_ID")
    secret_key = _required("ARTIFACT_STORAGE_S3_SECRET_ACCESS_KEY")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=boto3.session.Config(signature_version="s3v4"),
    )
    created = False
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        create_args: dict[str, object] = {"Bucket": bucket}
        if region != "us-east-1":
            create_args["CreateBucketConfiguration"] = {"LocationConstraint": region}
        client.create_bucket(**create_args)
        created = True
        client.head_bucket(Bucket=bucket)
    sample = client.list_objects_v2(Bucket=bucket, MaxKeys=1)
    return {
        "status": "ok",
        "endpoint_host": urlsplit(endpoint).hostname,
        "bucket": bucket,
        "created": created,
        "object_sample_count": len(sample.get("Contents", [])),
    }


def main() -> int:
    try:
        print(json.dumps(_ensure_bucket(), sort_keys=True))
    except (BotoCoreError, OSError, ValueError):
        print(json.dumps({"status": "failed", "operation": "ensure-artifact-bucket"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
