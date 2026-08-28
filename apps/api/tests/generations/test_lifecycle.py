from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Self
from uuid import uuid4

import pytest

from app.audit.writer import AuditContext
from app.generations.errors import GenerationStateConflictError
from app.generations.lifecycle import ArtifactCleanupService, GenerationLifecycleService


class _Result:
    def __init__(self, *, scalar: object | None = None, first: object | None = None) -> None:
        self._scalar = scalar
        self._first = first
        self.rowcount = 1

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def first(self) -> object | None:
        return self._first


class _Session:
    def __init__(self, job: object) -> None:
        self.job = job
        self.audit_rows: list[object] = []
        self.execute_count = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> Self:
        return self

    async def execute(self, _statement: object) -> _Result:
        self.execute_count += 1
        return _Result(scalar=self.job)

    def add(self, row: object) -> None:
        self.audit_rows.append(row)


@pytest.mark.asyncio
async def test_cancel_is_limited_to_pre_provider_accepted_state() -> None:
    now = datetime.now(UTC)
    job = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        actor_user_id=uuid4(),
        job_id=uuid4(),
        status="accepted",
        deleted_at=None,
        completed_at=None,
        updated_at=now,
        error_code=None,
        reconciliation_status="not_required",
    )
    session = _Session(job)
    service = GenerationLifecycleService(session)  # type: ignore[arg-type]

    await service.cancel_accepted(
        tenant_id=job.tenant_id,
        actor_user_id=job.actor_user_id,
        job_id=job.job_id,
        audit_context=AuditContext(),
    )

    assert job.status == "cancelled"
    assert job.completed_at is not None
    assert [row.action for row in session.audit_rows] == ["generation.cancel"]

    running = SimpleNamespace(**{**job.__dict__, "status": "running", "completed_at": None})
    with pytest.raises(GenerationStateConflictError):
        await GenerationLifecycleService(_Session(running)).cancel_accepted(  # type: ignore[arg-type]
            tenant_id=running.tenant_id,
            actor_user_id=running.actor_user_id,
            job_id=running.job_id,
            audit_context=AuditContext(),
        )


@pytest.mark.asyncio
async def test_soft_delete_hides_terminal_job_and_enqueues_artifacts() -> None:
    job = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        actor_user_id=uuid4(),
        job_id=uuid4(),
        status="succeeded",
        deleted_at=None,
        updated_at=datetime.now(UTC),
    )
    session = _Session(job)

    await GenerationLifecycleService(session).soft_delete(  # type: ignore[arg-type]
        tenant_id=job.tenant_id,
        actor_user_id=job.actor_user_id,
        job_id=job.job_id,
        audit_context=AuditContext(),
    )

    assert job.deleted_at is not None
    assert session.execute_count == 2
    assert [row.action for row in session.audit_rows] == ["generation.delete"]


class _CleanupSessions:
    def __init__(self, artifact: object, job_id: object) -> None:
        self.artifact = artifact
        self.job_id = job_id
        self.calls = 0

    def __call__(self) -> _Session:
        parent = self

        class CleanupSession(_Session):
            async def execute(self, _statement: object) -> _Result:
                parent.calls += 1
                if parent.calls == 1:
                    return _Result(first=(parent.artifact, parent.job_id))
                return _Result()

        return CleanupSession(SimpleNamespace())


class _Storage:
    storage_provider = "s3"

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_object(self, *, object_key: str, **_kwargs: object) -> None:
        self.deleted.append(object_key)


@pytest.mark.asyncio
async def test_cleanup_deletes_object_then_tombstones_row() -> None:
    artifact = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        generation_job_id=uuid4(),
        object_key="tenant/job/output.png",
        status="expired",
        updated_at=datetime.now(UTC),
    )
    storage = _Storage()
    sessions = _CleanupSessions(artifact, uuid4())
    cleanup = ArtifactCleanupService(sessions, storage)  # type: ignore[arg-type]

    assert await cleanup.run_once() is True
    assert artifact.status == "delete_pending"
    assert storage.deleted == [artifact.object_key]
