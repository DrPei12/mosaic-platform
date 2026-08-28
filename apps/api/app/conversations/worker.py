"""Durable, fenced text-chat execution orchestration.

The worker deliberately has no surrounding database transaction.  Claim,
history loading, each delta, and every terminal transition are independent
short repository operations; the provider stream is consumed between those
operations.  A concrete PostgreSQL repository is responsible for implementing
the compare-and-set predicates described by :class:`ChatExecutionRepository`.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import UUID

from app.conversations.errors import ConversationInfrastructureError
from app.conversations.ports import (
    ChatBillingSettlementPort,
    ChatExecutionRecord,
    ChatExecutionRepository,
    ChatInferenceExecutorPort,
    ChatLeaseCheck,
    ChatRequestRecord,
    ChatStreamNotifier,
    ChatUsageRecord,
)
from app.infrastructure.concurrency import (
    ConcurrencySaturated,
    ConcurrencyUnavailable,
    RedisLeaseGuard,
    RedisLeaseSemaphore,
    acquire_deployment_admission,
)
from app.observability.metrics import record_worker_outcome
from app.providers.errors import ProviderError
from app.providers.ports import (
    ChatMessage,
    TextCompletionRequest,
    TextGenerationPort,
    TextStreamChunk,
    Usage,
)

_ERROR_CODE_RE = re.compile(r"[^A-Z0-9_]+")
_MAX_ERROR_CODE_LENGTH = 120
_UNCERTAIN_PROVIDER_CODES = frozenset(
    {
        "provider_submission_unknown",
        "submission_unknown",
    }
)
_DEFINITIVE_NO_SUBMISSION_CODES = frozenset({"provider_connection_error"})


@dataclass(frozen=True, slots=True)
class ChatWorkerDependencies:
    """Composition boundary for the standalone chat worker.

    ``executor`` retains the old explicit extension seam used by the API
    foundation tests.  The real path requires all three durable dependencies:
    an execution repository, a trusted text provider and billing settlement.
    """

    executor: ChatInferenceExecutorPort | None = None
    repository: ChatExecutionRepository | None = None
    text_generation: TextGenerationPort | None = None
    billing: ChatBillingSettlementPort | None = None
    worker_id: str = "chat-worker"
    lease_seconds: int = 60
    concurrency: RedisLeaseSemaphore | None = None
    concurrency_lease_seconds: float = 120.0
    concurrency_renewal_interval_seconds: float | None = None
    concurrency_retry_delay_seconds: float = 2.0
    stream_notifier: ChatStreamNotifier | None = None
    temperature: float | None = None
    max_completion_tokens: int | None = None


@dataclass(slots=True)
class _ChatStreamState:
    current: ChatExecutionRecord
    provider_request_id: str | None
    content: str
    usage: Usage | None = None
    terminal_marked: bool = False


class DurableChatWorker:
    """Claim and execute one queued text request with a fenced lease."""

    def __init__(self, dependencies: ChatWorkerDependencies) -> None:
        if not dependencies.worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if dependencies.lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        if dependencies.concurrency_lease_seconds < 1:
            raise ValueError("concurrency lease must be at least one second")
        if dependencies.concurrency_renewal_interval_seconds is not None and (
            dependencies.concurrency_renewal_interval_seconds <= 0
        ):
            raise ValueError("concurrency renewal interval must be positive")
        if dependencies.concurrency_retry_delay_seconds <= 0:
            raise ValueError("concurrency retry delay must be positive")
        self._dependencies = dependencies

    async def process(self, request: ChatRequestRecord) -> None:
        """Process a delivery for ``request`` without trusting its status.

        Queue envelopes are at-least-once and therefore untrusted hints.  The
        execution repository must re-read and claim the durable queued row via
        a compare-and-set.  The legacy explicit executor path is kept only for
        callers that deliberately compose it; it cannot be selected together
        with the durable path.
        """

        executor = self._dependencies.executor
        if executor is not None:
            try:
                await executor.execute(request=request)
            except Exception:
                record_worker_outcome(worker="chat", outcome="failure")
                raise
            record_worker_outcome(worker="chat", outcome="success")
            return

        repository, provider, billing, _semaphore = self._required_dependencies()
        execution = await repository.claim_queued(
            worker_id=self._dependencies.worker_id,
            lease_seconds=self._dependencies.lease_seconds,
            tenant_id=request.tenant_id,
            request_id=request.request_id,
        )
        if execution is None:
            return
        await self._execute_claimed(execution, repository, provider, billing)

    async def run_once(self, *, tenant_id: UUID | None = None) -> bool:
        """Claim and process one queued row; return whether work was claimed."""

        if self._dependencies.executor is not None:
            raise ConversationInfrastructureError("CHAT_WORKER_CLAIM_UNAVAILABLE")
        repository, provider, billing, _semaphore = self._required_dependencies()
        execution = await repository.claim_queued(
            worker_id=self._dependencies.worker_id,
            lease_seconds=self._dependencies.lease_seconds,
            tenant_id=tenant_id,
        )
        if execution is None:
            return False
        await self._execute_claimed(execution, repository, provider, billing)
        return True

    def _required_dependencies(
        self,
    ) -> tuple[
        ChatExecutionRepository,
        TextGenerationPort,
        ChatBillingSettlementPort,
        RedisLeaseSemaphore,
    ]:
        missing = [
            name
            for name, value in (
                ("repository", self._dependencies.repository),
                ("text_generation", self._dependencies.text_generation),
                ("billing", self._dependencies.billing),
                ("concurrency", self._dependencies.concurrency),
            )
            if value is None
        ]
        if missing:
            raise ConversationInfrastructureError(
                "CHAT_WORKER_NOT_CONFIGURED",
            )
        repository = self._dependencies.repository
        provider = self._dependencies.text_generation
        billing = self._dependencies.billing
        semaphore = self._dependencies.concurrency
        assert repository is not None
        assert provider is not None
        assert billing is not None
        assert semaphore is not None
        return repository, provider, billing, semaphore

    async def _execute_claimed(
        self,
        execution: ChatExecutionRecord,
        repository: ChatExecutionRepository,
        provider: TextGenerationPort,
        billing: ChatBillingSettlementPort,
    ) -> None:
        # ``execution`` already carries the running lease issued by claim.  No
        # transaction is opened in this method or across provider.stream().
        if execution.status != "running" or execution.lease_token is None:
            return

        if execution.reservation_id is None:
            await self._fail(
                execution=execution,
                repository=repository,
                billing=billing,
                expected_sequence=execution.last_event_sequence + 1,
                error_code="CHAT_BILLING_RESERVATION_MISSING",
                error_details=None,
                provider_request_id=execution.provider_request_id,
                reserved=False,
            )
            return
        reserved = True

        if await self._stop_if_requested(
            execution,
            repository,
            billing,
            content="",
            reserved=reserved,
        ):
            return

        try:
            completion = _completion_request(execution, self._dependencies)
        except (TypeError, ValueError):
            await self._fail(
                execution=execution,
                repository=repository,
                billing=billing,
                expected_sequence=execution.last_event_sequence + 1,
                error_code="CHAT_HISTORY_INVALID",
                error_details=None,
                provider_request_id=execution.provider_request_id,
                reserved=reserved,
            )
            return

        try:
            admission = await self._acquire_admission(execution)
        except ConcurrencyUnavailable:
            await self._requeue_after_saturation(execution, repository)
            raise
        if admission is None:
            await self._requeue_after_saturation(execution, repository)
            raise ConcurrencySaturated(
                retry_after_seconds=self._dependencies.concurrency_retry_delay_seconds,
            )

        submission_attempted = False
        provider_request_id = execution.provider_request_id
        content = ""
        usage: Usage | None = None
        current = execution
        terminal_marked = False
        stream_state = _ChatStreamState(
            current=current,
            provider_request_id=provider_request_id,
            content=content,
        )
        try:
            async with admission:
                if await self._stop_if_requested(
                    execution,
                    repository,
                    billing,
                    content="",
                    reserved=reserved,
                ):
                    return

                # ``stream`` is an async generator. The chargeable POST occurs
                # on the first iteration, so no retry is ever attempted here.
                submission_attempted = True
                stream_state = await admission.run(
                    self._consume_stream(
                        state=stream_state,
                        repository=repository,
                        provider=provider,
                        billing=billing,
                        completion=completion,
                        reserved=reserved,
                    )
                )
                current = stream_state.current
                provider_request_id = stream_state.provider_request_id
                content = stream_state.content
                usage = stream_state.usage
                terminal_marked = stream_state.terminal_marked
                if terminal_marked:
                    return

                usage_record = ChatUsageRecord(
                    request_db_id=current.request_db_id,
                    request_id=current.request_id,
                    tenant_id=current.tenant_id,
                    deployment_id=current.deployment.deployment_id,
                    provider_request_id=provider_request_id,
                    usage=usage or Usage(),
                )
                final_check = await repository.check_lease_and_stop(execution=current)
                if not final_check.lease_valid:
                    return
                if final_check.stop_requested:
                    await self._stop_if_requested(
                        current,
                        repository,
                        billing,
                        content=content,
                        reserved=reserved,
                        force=True,
                    )
                    terminal_marked = True
                    return
                completed = await repository.mark_completed(
                    execution=current,
                    expected_sequence=current.last_event_sequence + 1,
                    content=content,
                    provider_request_id=provider_request_id,
                    usage=usage_record,
                )
                if not completed:
                    return
                terminal_marked = True
                await self._notify_stream(
                    execution=current,
                    sequence=current.last_event_sequence + 1,
                )
            # Capture follows the durable terminal event.  The billing
            # adapter calculates the charge from the accepted PriceVersion
            # and this actual usage; it is idempotent and never reserves.
            await billing.capture(execution=current, usage=usage_record)
            record_worker_outcome(worker="chat", outcome="success")
        except ProviderError as exc:
            current = stream_state.current
            provider_request_id = stream_state.provider_request_id
            content = stream_state.content
            if terminal_marked:
                record_worker_outcome(worker="chat", outcome="failure")
                raise
            await self._provider_failure(
                current=current,
                repository=repository,
                billing=billing,
                provider_request_id=provider_request_id or exc.request_id,
                error_code=exc.code,
                error_details=exc.diagnostic_dict(),
                submitted_unknown=submission_attempted and _is_submission_unknown(exc),
                reserved=reserved,
            )
        except (ConcurrencySaturated, ConcurrencyUnavailable):
            raise
        except Exception:
            current = stream_state.current
            provider_request_id = stream_state.provider_request_id
            content = stream_state.content
            if terminal_marked:
                record_worker_outcome(worker="chat", outcome="failure")
                raise
            await self._provider_failure(
                current=current,
                repository=repository,
                billing=billing,
                provider_request_id=provider_request_id,
                error_code="CHAT_PROVIDER_ERROR",
                error_details=None,
                submitted_unknown=submission_attempted,
                reserved=reserved,
            )

    async def _consume_stream(
        self,
        *,
        state: _ChatStreamState,
        repository: ChatExecutionRepository,
        provider: TextGenerationPort,
        billing: ChatBillingSettlementPort,
        completion: TextCompletionRequest,
        reserved: bool,
    ) -> _ChatStreamState:
        stream: AsyncIterator[TextStreamChunk] | None = None
        try:
            stream = provider.stream(completion)
            async for chunk in stream:
                check = await repository.check_lease_and_stop(execution=state.current)
                if not check.lease_valid:
                    return state
                if check.stop_requested:
                    await self._stop_if_requested(
                        state.current,
                        repository,
                        billing,
                        content=state.content,
                        reserved=reserved,
                        force=True,
                    )
                    state.terminal_marked = True
                    return state

                state.provider_request_id = _coherent_provider_request_id(
                    state.provider_request_id,
                    chunk.request_id,
                )
                if chunk.usage is not None:
                    state.usage = chunk.usage
                if not chunk.delta:
                    continue
                event = await repository.append_delta(
                    execution=state.current,
                    expected_sequence=state.current.last_event_sequence + 1,
                    delta=chunk.delta,
                    provider_request_id=state.provider_request_id,
                )
                if event is None:
                    return state
                state.content += chunk.delta
                state.current = replace(
                    state.current,
                    last_event_sequence=event.sequence,
                    provider_request_id=state.provider_request_id,
                )
                await self._notify_stream(
                    execution=state.current,
                    sequence=event.sequence,
                )
            return state
        finally:
            if stream is not None:
                await _close_stream(stream)

    async def _acquire_admission(
        self,
        execution: ChatExecutionRecord,
    ) -> RedisLeaseGuard | None:
        semaphore = self._dependencies.concurrency
        if semaphore is None:
            raise ConversationInfrastructureError("CHAT_CONCURRENCY_NOT_CONFIGURED")
        return await acquire_deployment_admission(
            semaphore,
            tenant_id=execution.tenant_id,
            deployment_id=execution.deployment.deployment_id,
            limit=execution.deployment.concurrency_limit,
            ttl_seconds=self._dependencies.concurrency_lease_seconds,
            renewal_interval_seconds=self._dependencies.concurrency_renewal_interval_seconds,
        )

    async def _requeue_after_saturation(
        self,
        execution: ChatExecutionRecord,
        repository: ChatExecutionRepository,
    ) -> None:
        requeue = getattr(repository, "requeue_claimed", None)
        if not callable(requeue):
            raise ConversationInfrastructureError("CHAT_CONCURRENCY_REQUEUE_UNAVAILABLE")
        if not await requeue(execution=execution):
            raise ConversationInfrastructureError("CHAT_CONCURRENCY_REQUEUE_FAILED")

    async def _provider_failure(
        self,
        *,
        current: ChatExecutionRecord,
        repository: ChatExecutionRepository,
        billing: ChatBillingSettlementPort,
        provider_request_id: str | None,
        error_code: str,
        error_details: Mapping[str, object] | None,
        submitted_unknown: bool,
        reserved: bool,
    ) -> None:
        if submitted_unknown:
            # There is no safe terminal SSE event: the remote POST may have
            # succeeded.  Leave the row for reconciliation and do not release
            # or re-submit the reservation.
            marked = await repository.mark_submitted_unknown(
                execution=current,
                provider_request_id=provider_request_id,
                error_code=_safe_error_code(error_code, fallback="CHAT_SUBMISSION_UNKNOWN"),
            )
            if marked:
                record_worker_outcome(worker="chat", outcome="submitted_unknown")
                await self._notify_stream(
                    execution=current,
                    sequence=current.last_event_sequence + 1,
                )
            return

        await self._fail(
            execution=current,
            repository=repository,
            billing=billing,
            expected_sequence=current.last_event_sequence + 1,
            error_code=error_code,
            error_details=error_details,
            provider_request_id=provider_request_id,
            reserved=reserved,
        )

    async def _fail(
        self,
        *,
        execution: ChatExecutionRecord,
        repository: ChatExecutionRepository,
        billing: ChatBillingSettlementPort,
        expected_sequence: int,
        error_code: str,
        error_details: Mapping[str, object] | None,
        provider_request_id: str | None,
        reserved: bool,
    ) -> None:
        marked = await repository.mark_failed(
            execution=execution,
            expected_sequence=expected_sequence,
            error_code=_safe_error_code(error_code, fallback="CHAT_PROVIDER_ERROR"),
            error_details=_safe_error_details(error_details),
            provider_request_id=provider_request_id,
        )
        if marked:
            record_worker_outcome(worker="chat", outcome="failure")
            await self._notify_stream(
                execution=execution,
                sequence=expected_sequence,
            )
            if reserved:
                await billing.release(execution=execution)

    async def _stop_if_requested(
        self,
        execution: ChatExecutionRecord,
        repository: ChatExecutionRepository,
        billing: ChatBillingSettlementPort,
        *,
        content: str,
        reserved: bool = False,
        force: bool = False,
    ) -> bool:
        check: ChatLeaseCheck = (
            ChatLeaseCheck(lease_valid=True, stop_requested=True)
            if force
            else await repository.check_lease_and_stop(execution=execution)
        )
        if not check.lease_valid:
            return True
        if not check.stop_requested:
            return False
        marked = await repository.mark_stopped(
            execution=execution,
            expected_sequence=execution.last_event_sequence + 1,
            content=content,
        )
        if marked:
            record_worker_outcome(worker="chat", outcome="success")
            await self._notify_stream(
                execution=execution,
                sequence=execution.last_event_sequence + 1,
            )
            if reserved:
                await billing.release(execution=execution)
        return True

    async def _notify_stream(
        self,
        *,
        execution: ChatExecutionRecord,
        sequence: int,
    ) -> None:
        notifier = self._dependencies.stream_notifier
        if notifier is None or sequence < 0:
            return
        try:
            await notifier.publish(
                tenant_id=execution.tenant_id,
                request_id=execution.request_id,
                sequence=sequence,
            )
        except Exception:  # noqa: BLE001 - committed DB state is authoritative
            return


def _completion_request(
    execution: ChatExecutionRecord,
    dependencies: ChatWorkerDependencies,
) -> TextCompletionRequest:
    messages: list[ChatMessage] = []
    for item in execution.history:
        if item.message_id == execution.message_id:
            # 0005 creates the assistant target as an empty streaming row; it
            # is not part of the prompt sent back to the provider.
            continue
        if item.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("unsupported chat history role")
        if not item.content.strip():
            continue
        messages.append(ChatMessage(role=cast(Any, item.role), content=item.content))
    return TextCompletionRequest(
        model=execution.deployment.provider_model_id,
        messages=tuple(messages),
        temperature=_config_float(
            execution.deployment.routing_config,
            "temperature",
            dependencies.temperature,
        ),
        max_completion_tokens=_config_int(
            execution.deployment.routing_config,
            "max_completion_tokens",
            dependencies.max_completion_tokens,
        ),
    )


def _config_float(
    config: Mapping[str, object],
    key: str,
    fallback: float | None,
) -> float | None:
    value = config.get(key, fallback)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _config_int(
    config: Mapping[str, object],
    key: str,
    fallback: int | None,
) -> int | None:
    value = config.get(key, fallback)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _coherent_provider_request_id(previous: str | None, current: str) -> str:
    if not current:
        raise ValueError("provider request id must not be blank")
    if previous is not None and previous != current:
        raise ValueError("provider request id changed during one stream")
    return current


def _is_submission_unknown(error: ProviderError) -> bool:
    code = error.code.lower()
    if code in _UNCERTAIN_PROVIDER_CODES:
        return True
    # The DashScope adapter emits this code only for ConnectError/
    # ConnectTimeout, before an HTTP connection was established. Releasing
    # that hold avoids turning a provider outage into a wallet-exhaustion path.
    if code in _DEFINITIVE_NO_SUBMISSION_CODES:
        return False
    # A protocol/transport failure without a definitive response, an HTTP 408,
    # or a server-side 5xx can happen after the chargeable POST reached the
    # provider. Preserve the hold for reconciliation and never retry it.
    return error.status_code is None or error.status_code == 408 or error.status_code >= 500


def _safe_error_code(value: str, *, fallback: str) -> str:
    normalized = _ERROR_CODE_RE.sub("_", value.upper()).strip("_")
    return (normalized or fallback)[:_MAX_ERROR_CODE_LENGTH]


def _safe_error_details(value: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if value is None:
        return None
    safe: dict[str, object] = {}
    for key in ("code", "phase", "retryable", "status_code", "request_id"):
        item = value.get(key)
        if isinstance(item, (str, bool, int)) or item is None:
            safe[key] = item
    return safe


async def _close_stream(stream: AsyncIterator[TextStreamChunk] | None) -> None:
    if stream is None:
        return
    close = getattr(stream, "aclose", None)
    if close is None:
        return
    result = close()
    if hasattr(result, "__await__"):
        await cast(Any, result)


__all__ = ["ChatWorkerDependencies", "DurableChatWorker"]
