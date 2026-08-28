# MOSAIC Phase 3 Production Backend Implementation Plan

**Goal:** Deliver a production-oriented, tenant-isolated MOSAIC vertical slice backed by PostgreSQL and real Bailian provider calls, then extend the same job, usage and storage model to image, video and audio.

**Architecture:** Modular FastAPI monolith for synchronous APIs and domain transactions, PostgreSQL as the source of truth, Redis for bounded concurrency, RabbitMQ/Celery for durable media execution, S3-compatible object storage for durable artifacts, and explicit Provider adapters for OpenAI-compatible text plus native Bailian media protocols.

**Hard acceptance rule:** Test doubles may validate local mechanics, but no modality is accepted without a real Bailian live smoke. There is no automatic Demo fallback in API mode.

**Worker configuration:** Every implementation and review subagent uses `gpt-5.6-luna` with `max` reasoning.

## Milestone 0: Isolation, secrets and official contracts

- [x] Create branch `codex/product-production-backend` in an isolated worktree.
- [x] Store `DASHSCOPE_API_KEY` in the Windows user environment, never in the repository.
- [x] Confirm official endpoint and model contracts for text, image, video and TTS.
- [ ] Obtain the production Workspace ID and dedicated API host before load testing.
- [ ] Restore local outbound TLS/proxy connectivity and run the four real smoke calls.

Live smoke models and minimum-cost inputs:

- Text: `qwen3.5-plus`, one short deterministic response.
- Image: `qwen-image-3.0-pro`, one image.
- Video: `wan2.7-t2v`, 2 seconds, 720P, one task.
- Audio: `qwen3-tts-flash` (public product: Qwen3-TTS Flash), one short Chinese sentence, `Cherry`.

## Milestone 1: Provider foundation

Files:

- Modify `apps/api/pyproject.toml` and `apps/api/uv.lock`.
- Modify `apps/api/app/core/settings.py` and `apps/api/.env.example` for non-secret config only.
- Create `apps/api/app/providers/contracts.py`.
- Create `apps/api/app/providers/errors.py`.
- Create `apps/api/app/providers/openai_compatible.py`.
- Create `apps/api/app/providers/bailian.py`.
- Create `apps/api/app/providers/registry.py`.
- Create `apps/api/scripts/provider_smoke.py`.
- Create focused unit and live tests.

Acceptance:

- Provider credentials are loaded from process environment only.
- Secret values are redacted from repr, logs and errors.
- Text streaming, image sync result, video submit/poll and TTS result parse exact official shapes.
- Chargeable POST requests do not perform blind retries.
- Live script emits only sanitized summaries and writes artifacts outside the repository.

Implementation status (2026-08-24): provider code, protocol tests, secret
redaction and the opt-in live runner are complete. The live gate remains failed
because all four calls currently stop at local connection establishment before
an HTTP response or Provider request ID is received.

## Milestone 2: PostgreSQL tenant and identity foundation

Files:

- Add SQLAlchemy metadata, models and async session/transaction helpers.
- Add a new Alembic revision after `20260820_0001`.
- Add native auth contracts, routes, service and repository.
- Extend Compose with Redis; RabbitMQ/MinIO are added before media jobs.

Tables in the first migration:

- tenant, user, membership, auth_session
- product_model, provider_endpoint, model_deployment
- tenant_model_entitlement
- conversation, message, inference_request
- idempotency_record, audit_event

Acceptance:

- Argon2id password hashing and hashed opaque session tokens.
- Secure cookie and CSRF behavior covered by API tests.
- Every tenant-scoped repository requires an authenticated tenant context.
- Cross-tenant IDs return not found/forbidden without data disclosure.
- Migration upgrade/downgrade and one-head checks pass on PostgreSQL 17.

Implementation status (2026-08-24): the PostgreSQL-specific metadata and
Alembic revision are complete and compile offline with one migration head.
Because this device currently has neither Docker nor a PostgreSQL server, real
PostgreSQL upgrade/downgrade remains an unpassed integration gate.

## Milestone 3: Real text conversation vertical slice

- Implement the existing Web adapter endpoints without changing their public paths.
- Persist conversations, messages, inference request state and monotonic SSE event sequence.
- Enforce `Idempotency-Key` by tenant, actor and operation with request hash conflicts.
- Stream `qwen3.5-plus` through the OpenAI-compatible Provider adapter.
- Implement stop as a local cancellation intent plus provider connection cancellation; preserve already emitted text.
- Implement resume from persisted events and regenerate without duplicating the user message.
- Record normalized token usage and Provider request IDs.

Acceptance:

- Refresh resumes from PostgreSQL, not browser Demo state.
- Two concurrent sends to one conversation produce one accepted request and one `CONVERSATION_BUSY`.
- No Provider body, endpoint or credential leaks through the public error contract.
- Real browser E2E uses API mode and a real Bailian response.

## Milestone 4: Usage reservation and ledger

- Add wallet account, balance reservation, immutable ledger entry and usage record tables.
- Reserve before Provider submission and settle/release after terminal state.
- Store price version and integer money units.
- Add reconciliation jobs for stale reservations and submitted-unknown requests.
- Add usage and wallet read APIs; no online payment claim yet.

Acceptance:

- Same idempotency key cannot reserve or charge twice.
- Concurrent requests cannot overspend the same balance.
- Ledger projection is rebuildable and invariant checks are tested.

## Milestone 5: Durable media jobs

- Add generation job, artifact and outbox tables.
- Add RabbitMQ, Celery worker and transactional outbox relay.
- Add Redis lease semaphores for tenant/deployment concurrency.
- Add S3-compatible storage abstraction and MinIO for local development.
- Implement real Qwen Image, Wan 2.7 and Qwen3-TTS adapters through the shared job state machine.
- Download 24-hour Provider result URLs immediately and persist them in object storage.

Acceptance:

- Duplicate queue delivery does not submit or charge twice.
- Worker crash/restart resumes from durable job state.
- Video poll uses bounded exponential intervals and a final deadline.
- Every modality completes one real live smoke and one API-to-object-storage integration flow.

## Milestone 6: Frontend production cutover

- Make API mode the default and Demo mode explicit-only.
- Remove API catalog dependence on Demo model IDs.
- Keep presentation metadata keyed by stable public product ID in a production-safe registry.
- Replace Demo login gate with server session behavior.
- Connect image/video/audio workspaces to generation job APIs.
- Connect generation history, usage and wallet pages to real data.

Acceptance:

- Production build cannot silently fall back to Demo.
- Catalog availability comes from backend route health, not static fixtures.
- Browser E2E covers registration/login, catalog, real text chat and one media job.
- Existing visual fidelity, accessibility and responsive geometry gates remain green.

## Verification commands

```powershell
pnpm verify:web
pnpm --filter @mosaic/web test:e2e

uv run --project apps/api pytest -q
uv run --project apps/api ruff check apps/api/app apps/api/tests apps/api/scripts
uv run --project apps/api mypy apps/api/app apps/api/migrations apps/api/scripts
uv run --project apps/api alembic -c apps/api/alembic.ini heads
```

The live Provider gate is invoked explicitly and fails if `DASHSCOPE_API_KEY` is absent. It may be skipped in untrusted pull-request CI, but a skipped live gate never counts as production acceptance.
