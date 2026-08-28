from __future__ import annotations

from uuid import uuid4

import pytest

from app.generations.errors import GenerationInfrastructureError
from app.generations.repository import OutboxRecord
from app.generations.worker import DurableGenerationWorker, WorkerDependencies


class _Repository:
    pass


@pytest.mark.asyncio
async def test_worker_fails_closed_when_durable_dependencies_are_missing() -> None:
    worker = DurableGenerationWorker(_Repository(), WorkerDependencies())  # type: ignore[arg-type]
    event = OutboxRecord(
        event_id=uuid4(),
        tenant_id=uuid4(),
        aggregate_type="generation_job",
        aggregate_id=uuid4(),
        event_type="generation.accepted",
        aggregate_version=1,
        payload={"job_id": str(uuid4())},
        attempts=1,
    )

    with pytest.raises(GenerationInfrastructureError) as error:
        await worker.process(event)
    assert error.value.code == "GENERATION_WORKER_NOT_CONFIGURED"
    assert "missing" in (error.value.diagnostic_details or {})
