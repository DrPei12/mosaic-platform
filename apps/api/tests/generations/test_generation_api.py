from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.api.exception_handlers import register_exception_handlers
from app.api.generations import (
    get_generation_artifact_storage,
    get_generation_lifecycle_service,
    get_generation_service,
    require_generation_submission_enabled,
    router,
)
from app.auth.dependencies import current_auth, require_authenticated_csrf
from app.contracts.generations import CreateGenerationRequest
from app.generations.errors import GenerationNotFoundError
from app.generations.repository import AcceptedGeneration, GenerationRecord
from app.infrastructure.database import get_db_session

TENANT_ID = UUID("00000000-0000-0000-0000-000000000051")
TENANT_B = UUID("00000000-0000-0000-0000-000000000061")
USER_ID = UUID("00000000-0000-0000-0000-000000000052")
USER_B = UUID("00000000-0000-0000-0000-000000000062")


def _record() -> GenerationRecord:
    now = datetime.now(UTC)
    return GenerationRecord(
        db_id=uuid4(),
        job_id=UUID("00000000-0000-0000-0000-000000000053"),
        tenant_id=TENANT_ID,
        actor_user_id=USER_ID,
        product_model_id="qwen-3-5-plus",
        modality="text",
        status="accepted",
        request_payload={"input": {"prompt": "hello"}},
        created_at=now,
        updated_at=now,
        completed_at=None,
        error_code=None,
        model_deployment_id=uuid4(),
        artifacts=(),
    )


class FakeGenerationService:
    def __init__(self) -> None:
        self.record = _record()
        self.received_tenant: UUID | None = None
        self.received_user: UUID | None = None
        self.received_get_user: UUID | None = None

    def _check_scope(self, kwargs: dict[str, object]) -> None:
        if kwargs["tenant_id"] != TENANT_ID or kwargs["actor_user_id"] != USER_ID:
            raise GenerationNotFoundError()

    async def accept(self, *, tenant_id, actor_user_id, request):
        self.received_tenant = tenant_id
        self.received_user = actor_user_id
        assert isinstance(request, CreateGenerationRequest)
        return AcceptedGeneration(record=self.record, replayed=False)

    async def get(self, *, tenant_id, actor_user_id, job_id):
        self.received_get_user = actor_user_id
        self._check_scope(
            {
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
            }
        )
        assert job_id == self.record.job_id
        return self.record.public_response()

    async def list_recent(self, *, tenant_id, actor_user_id, limit=50):
        self.received_get_user = actor_user_id
        if tenant_id != TENANT_ID or actor_user_id != USER_ID:
            return []
        return [self.record.public_response() for _ in range(min(limit, 1))]


class _LifecycleService:
    def __init__(self) -> None:
        self.cancelled: tuple[UUID, UUID, UUID] | None = None
        self.deleted: tuple[UUID, UUID, UUID] | None = None

    async def cancel_accepted(self, *, tenant_id, actor_user_id, job_id, audit_context):
        assert audit_context is not None
        self.cancelled = (tenant_id, actor_user_id, job_id)

    async def soft_delete(self, *, tenant_id, actor_user_id, job_id, audit_context):
        assert audit_context is not None
        self.deleted = (tenant_id, actor_user_id, job_id)


class _ArtifactResult:
    def __init__(self, row: object) -> None:
        self._row = row

    def first(self) -> object:
        return self._row


class _ArtifactSession:
    def __init__(self, row: object, *, allowed: bool = True) -> None:
        self._row = row
        self._allowed = allowed
        self.statement: object | None = None

    async def execute(self, statement: object) -> _ArtifactResult:
        self.statement = statement
        return _ArtifactResult(self._row if self._allowed else None)


class _StreamingArtifactStorage:
    storage_provider = "s3"

    def __init__(self, content: bytes) -> None:
        self._content = content
        self.received: tuple[UUID, UUID, str] | None = None

    async def open_stream(
        self,
        *,
        tenant_id: UUID,
        job_id: UUID,
        object_key: str,
    ) -> AsyncIterator[bytes]:
        self.received = (tenant_id, job_id, object_key)

        async def chunks() -> AsyncIterator[bytes]:
            yield self._content

        return chunks()


@pytest.mark.asyncio
async def test_generation_post_uses_auth_tenant_and_public_projection() -> None:
    service = FakeGenerationService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_authenticated_csrf] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID, role="member"),
    )
    app.dependency_overrides[current_auth] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID, role="member"),
    )
    app.dependency_overrides[get_generation_service] = lambda: service
    app.dependency_overrides[require_generation_submission_enabled] = lambda: None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/generations",
            json={
                "product_model_id": "qwen-3-5-plus",
                "modality": "text",
                "input": {"prompt": "hello"},
                "client_request_id": "client-1",
            },
        )

    assert response.status_code == 202
    assert service.received_tenant == TENANT_ID
    assert service.received_user == USER_ID
    assert response.headers["location"].endswith(str(service.record.job_id))
    body = response.json()
    assert body["status"] == "accepted"
    assert "provider_model_id" not in body
    assert "provider_task_id" not in body
    assert "object_key" not in body
    assert "signed_url" not in body


@pytest.mark.asyncio
async def test_generation_post_fails_closed_when_worker_stack_is_disabled() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[require_authenticated_csrf] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID, role="member"),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/generations",
            json={
                "product_model_id": "qwen-3-5-plus",
                "modality": "text",
                "input": {"prompt": "hello"},
                "client_request_id": "client-1",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "GENERATION_SUBMISSION_DISABLED"
    assert "details" not in response.json()["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("modality", "input_payload"),
    [
        ("text", {"prompt": "hello"}),
        ("image", {"prompt": "hello"}),
        ("audio", {"text": "hello"}),
        ("video", {"prompt": "hello"}),
    ],
)
async def test_generation_post_rejects_when_modality_worker_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    modality: str,
    input_payload: dict[str, str],
) -> None:
    import app.api.generations as generations_module

    service = FakeGenerationService()
    checked_modalities: list[str] = []

    async def worker_not_ready(modality: str) -> bool:
        checked_modalities.append(modality)
        return False

    monkeypatch.setattr(
        generations_module,
        "settings",
        SimpleNamespace(generation_submission_enabled=True),
    )
    monkeypatch.setattr(
        generations_module,
        "is_generation_worker_ready_for_modality",
        worker_not_ready,
    )

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[require_authenticated_csrf] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID, role="member"),
    )
    app.dependency_overrides[current_auth] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID, role="member"),
    )
    app.dependency_overrides[get_generation_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/generations",
            json={
                "product_model_id": "qwen-3-5-plus",
                "modality": modality,
                "input": input_payload,
                "client_request_id": "client-worker-missing",
            },
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "GENERATION_SUBMISSION_DISABLED"
    assert service.received_tenant is None
    assert checked_modalities == [modality]


@pytest.mark.asyncio
async def test_generation_post_rejects_public_provider_voice_identifier() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_authenticated_csrf] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID, role="member"),
    )
    app.dependency_overrides[require_generation_submission_enabled] = lambda: None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/generations",
            json={
                "product_model_id": "qwen3-tts-custom-voice",
                "modality": "audio",
                "input": {
                    "text": "hello",
                    "voice": "provider-secret-voice-id",
                },
                "client_request_id": "client-voice-1",
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_generation_get_is_tenant_bound_and_does_not_expose_internal_fields() -> None:
    service = FakeGenerationService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_authenticated_csrf] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID),
    )
    app.dependency_overrides[current_auth] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID, role="member"),
    )
    app.dependency_overrides[get_generation_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/generations/{service.record.job_id}")

    assert response.status_code == 200
    assert service.received_get_user == USER_ID
    body = response.json()
    assert body["product_model_id"] == "qwen-3-5-plus"
    assert set(body) == {
        "job_id",
        "product_model_id",
        "modality",
        "status",
        "created_at",
        "updated_at",
            "completed_at",
            "error_code",
            "reconciliation_pending",
            "artifacts",
    }


@pytest.mark.asyncio
async def test_artifact_api_streams_from_configured_storage_without_provider_url() -> None:
    job_id = uuid4()
    artifact_id = uuid4()
    object_key = f"{TENANT_ID}/{job_id}/output-{'a' * 32}.png"
    content = b"artifact-from-object-storage"
    storage = _StreamingArtifactStorage(content)
    artifact = SimpleNamespace(
        id=artifact_id,
        tenant_id=TENANT_ID,
        storage_provider="s3",
        status="ready",
        object_key=object_key,
        mime_type="image/png",
        size_bytes=len(content),
    )
    session = _ArtifactSession((artifact, SimpleNamespace()))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_auth] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID, role="member"),
    )
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_generation_artifact_storage] = lambda: storage

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/generations/{job_id}/artifacts/{artifact_id}")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["cache-control"] == "no-store"
    assert "provider" not in response.headers["content-disposition"]
    assert storage.received == (TENANT_ID, job_id, object_key)
    assert session.statement is not None
    assert "generation_jobs.actor_user_id" in str(session.statement).lower()


@pytest.mark.asyncio
async def test_cancel_and_delete_are_csrf_and_actor_scoped() -> None:
    lifecycle = _LifecycleService()
    auth = cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID, role="member"),
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_authenticated_csrf] = lambda: auth
    app.dependency_overrides[get_generation_lifecycle_service] = lambda: lifecycle
    job_id = uuid4()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        cancelled = await client.post(f"/api/v1/generations/{job_id}/cancel")
        deleted = await client.delete(f"/api/v1/generations/{job_id}")

    assert cancelled.status_code == 204
    assert deleted.status_code == 204
    assert lifecycle.cancelled == (TENANT_ID, USER_ID, job_id)
    assert lifecycle.deleted == (TENANT_ID, USER_ID, job_id)


@pytest.mark.asyncio
async def test_generation_api_passes_auth_actor_to_list_and_get() -> None:
    service = FakeGenerationService()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[current_auth] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_ID, role="member"),
    )
    app.dependency_overrides[get_generation_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        listed = await client.get("/api/v1/generations")
        fetched = await client.get(f"/api/v1/generations/{service.record.job_id}")

    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert fetched.status_code == 200
    assert service.received_get_user == USER_ID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tenant_id", "user_id"),
    [(TENANT_B, USER_ID), (TENANT_ID, USER_B)],
)
async def test_generation_api_hides_cross_tenant_and_same_tenant_user_jobs(
    tenant_id: UUID,
    user_id: UUID,
) -> None:
    service = FakeGenerationService()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[current_auth] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=tenant_id, user_id=user_id, role="member"),
    )
    app.dependency_overrides[get_generation_service] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        listed = await client.get("/api/v1/generations")
        fetched = await client.get(f"/api/v1/generations/{service.record.job_id}")

    assert listed.status_code == 200
    assert listed.json() == []
    assert fetched.status_code == 404
    assert fetched.json()["error"]["code"] == "GENERATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_artifact_api_returns_404_for_another_actor_without_opening_storage() -> None:
    job_id = uuid4()
    artifact_id = uuid4()
    storage = _StreamingArtifactStorage(b"must-not-open")
    artifact = SimpleNamespace(
        id=artifact_id,
        tenant_id=TENANT_ID,
        storage_provider="s3",
        status="ready",
        object_key=f"{TENANT_ID}/{job_id}/output.png",
        mime_type="image/png",
        size_bytes=13,
    )
    session = _ArtifactSession((artifact, SimpleNamespace()), allowed=False)
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[current_auth] = lambda: cast(
        object,
        SimpleNamespace(tenant_id=TENANT_ID, user_id=USER_B, role="member"),
    )
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_generation_artifact_storage] = lambda: storage

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/api/v1/generations/{job_id}/artifacts/{artifact_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GENERATION_NOT_FOUND"
    assert storage.received is None
    assert session.statement is not None
    assert "generation_jobs.actor_user_id" in str(session.statement).lower()
