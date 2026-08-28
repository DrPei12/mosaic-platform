from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Self
from uuid import UUID

import pytest

from app.generations.repository import SqlAlchemyGenerationRepository

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
USER_ID = UUID("00000000-0000-0000-0000-000000000011")


class _Result:
    def __init__(
        self,
        *,
        rows: tuple[object, ...] = (),
        scalar_rows: tuple[object, ...] = (),
    ) -> None:
        self._rows = rows
        self._scalar_rows = scalar_rows

    def all(self) -> tuple[object, ...]:
        return self._rows

    def scalars(self) -> tuple[object, ...]:
        return self._scalar_rows


class _Transaction:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Session:
    def __init__(
        self,
        rows: tuple[tuple[object, object, object], ...],
        artifacts: tuple[object, ...],
        *,
        list_limit: int,
    ) -> None:
        self._rows = rows
        self._artifacts = artifacts
        self._list_limit = list_limit
        self.statements: list[object] = []

    def begin(self) -> _Transaction:
        return _Transaction()

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _Result(rows=self._rows[: self._list_limit])
        if len(self.statements) == 2:
            selected_job_ids = {
                job.id for job, _deployment, _product in self._rows[: self._list_limit]
            }
            return _Result(
                scalar_rows=tuple(
                    artifact
                    for artifact in self._artifacts
                    if artifact.generation_job_id in selected_job_ids
                )
            )
        raise AssertionError("generation list issued an unexpected query")


def _fixture_rows(
    count: int,
) -> tuple[tuple[tuple[object, object, object], ...], tuple[object, ...]]:
    now = datetime(2026, 8, 26, tzinfo=UTC)
    rows: list[tuple[object, object, object]] = []
    artifacts: list[object] = []
    for index in range(count):
        db_id = UUID(int=index + 1)
        rows.append(
            (
                SimpleNamespace(
                    id=db_id,
                    job_id=UUID(int=10_000 + index),
                    tenant_id=TENANT_ID,
                    actor_user_id=UUID(int=20_000 + index),
                    modality="image",
                    status="succeeded",
                    request_payload={"prompt": f"prompt-{index}"},
                    created_at=now,
                    updated_at=now,
                    completed_at=now,
                    error_code=None,
                    model_deployment_id=UUID(int=30_000 + index),
                    provider_request_id=None,
                    provider_task_id=None,
                ),
                SimpleNamespace(id=UUID(int=40_000 + index)),
                SimpleNamespace(model_key="qwen-image-3-0-pro"),
            )
        )
        artifacts.append(
            SimpleNamespace(
                id=UUID(int=50_000 + index),
                generation_job_id=db_id,
                kind="output",
                status="ready",
                mime_type="image/png",
                size_bytes=100 + index,
            )
        )
    return tuple(rows), tuple(artifacts)


@pytest.mark.asyncio
@pytest.mark.parametrize("job_count", [1, 80])
async def test_generation_list_batches_artifact_loading(job_count: int) -> None:
    rows, artifacts = _fixture_rows(job_count)
    session = _Session(rows, artifacts, list_limit=10)

    records = await SqlAlchemyGenerationRepository(session).list_recent(
        tenant_id=TENANT_ID,
        actor_user_id=USER_ID,
        limit=10,
    )

    assert len(records) == min(job_count, 10)
    assert len(session.statements) == 2
    assert "limit" in str(session.statements[0]).lower()
    assert "generation_artifacts.generation_job_id in" in str(session.statements[1]).lower()
    assert "generation_jobs.actor_user_id" in str(session.statements[0]).lower()
    assert len(records[0].artifacts) == 1
    assert records[0].artifacts[0].mime_type == "image/png"
