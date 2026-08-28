# Production hardening E10 integration receipt

Date: 2026-08-27

Branch: `codex/production-hardening`
Scope: isolated local staging and source-level release candidate

## Verdict

The E0-E10 production-hardening implementation is integrated and passes the
current source, database, browser, recovery, and native-runtime gates. This is
a stable release-candidate baseline, not a claim that the complete commercial
MOSAIC product is finished.

Provider routes remain fail-closed by default. A paid Provider gate is accepted
only when evidence is generated from the release candidate's clean commit, is
less than 24 hours old, covers text/image/video/audio, binds the catalog
manifest and smoke-script digests, and verifies with the protected HMAC key.
Evidence generated for one commit cannot activate a later commit.

## Integrated hardening

- Immutable model revision, routing policy, capability schema, price version,
  and accepted request snapshots.
- Invitation-only identity, one-time credentials, forced password change,
  session rotation/revocation, CSRF, RBAC, and same-user ownership checks.
- PostgreSQL RLS with separate owner, app, and BYPASSRLS worker roles. Runtime
  login now binds the tenant before tenant-scoped audit writes; restricted
  session state is read from the persisted user record.
- Atomic idempotency, balance reservation, request acceptance, outbox creation,
  worker-only settlement/release, and unknown-result reconciliation.
- Separate chat, media, and video consumers; fenced leases; independent
  media/video readiness; modality-specific admission before service or billing.
- S3-compatible artifact transfer and validation, tenant-authorized download,
  terminal soft delete, and crash-safe lifecycle cleanup.
- Redis-backed SSE wake-up with database replay as truth and bounded stream
  permits.
- JSON logging, protected low-cardinality metrics, alerts, dashboards, and
  operator runbooks.
- Non-root container definitions, explicit runtime roles, fail-closed release
  settings, HMAC receipts, image-digest contracts, and CI startup of the built
  Web image.
- PostgreSQL logical backup, MinIO mirror, restore into isolated targets, hash
  checks, migration-head verification, and object-count verification.

## Defects found by final runtime and independent review

1. Real app-role login originally failed when the audit row encountered RLS.
   The auth repository now binds the resolved tenant both before new
   transactions and inside an already-active public-auth transaction.
2. Persisted restricted sessions were incorrectly reconstructed as unrestricted.
   `current_auth` now returns the real password-change state.
3. Media and video consumers shared one heartbeat. They now have independent
   keys, health dependencies, metrics, and modality-level admission checks.
4. Production Compose omitted the session token pepper. It is now a required
   injected value, placeholder peppers fail closed, and readiness verifies the
   codec without exposing the secret.
5. Explicit Provider and session placeholders could pass configuration probes.
   Known placeholder values now fail closed.
6. Catalog activation evidence was shape-only. It is now bound to a clean Git
   commit, manifest digest, smoke-script SHA-256, freshness window, and HMAC.
7. Chargeable voice revalidation and full-stack smoke paths lacked uniform
   confirmation. Every Provider POST path now requires explicit charge intent.
8. Generation failures could expose internal codes, and audio cards contained
   a playback button with no source. User copy is now mapped through a closed
   presentation layer and the false control is removed.
9. Windows standalone output omitted the complete SWC helper runtime. The
   monorepo tracing root and narrow helper include are explicit; CI starts the
   built image before accepting image evidence.
10. Multi-tenant password change attempted cross-tenant audit writes inside one
    RLS-bound transaction. All of the user's sessions are still revoked, while
    per-session audit rows stay in the current tenant and the password event
    records aggregate cross-tenant counts.
11. A normal catalog seed could preserve an older active route. Conflict
    updates now force canonical degraded/disabled status before any
    current-commit activation.
12. Release receipt integrity previously covered only config/compose. Full
    acceptance now requires signed Provider evidence and built-Web startup,
    binds the image manifest to HEAD, includes artifact cleanup, and HMAC-seals
    the complete receipt; a separate verifier rejects tampering.
13. Empty HTTP 200 media or empty text could satisfy the old live shape check.
    Current evidence requires positive text length and positive downloaded
    bytes for every media modality.
14. Video artwork and inspiration tiles still used a play symbol without a
    source or action. Those false affordances and the explanatory placeholder
    beneath inspiration headings are removed.
15. The first real six-model smoke exposed an ambiguous ORM join in immutable
    catalog decision resolution. The query now has an explicit
    `ModelRevisions` root, a compile regression test, and a real API restart
    gate before the final clean-commit Provider rerun.

## Current evidence

| Gate | Result |
| --- | --- |
| API pytest with real PostgreSQL billing/RLS and real MinIO | `360 passed, 4 skipped` |
| Paid Provider cases | `4 skipped` pending final clean-commit live run |
| Ruff | PASS |
| mypy | PASS, 128 source files |
| Alembic | single head `20260826_0013` |
| Web Vitest | `298 passed` |
| Contracts | `52 passed` |
| Design tokens | `4 passed` |
| Web lint/typecheck/brand/boundaries/build | PASS |
| Playwright, four responsive projects | `108 passed` |
| Native API live/ready | `200 / 200` |
| Protected API metrics | unauthenticated `404`, authenticated `200` |
| Relay/worker metrics listeners | five listeners, all `200` |
| RabbitMQ topology smoke | PASS |
| Redis / MinIO health | `PONG / 200` |
| App database role | `NOSUPERUSER`, `NOBYPASSRLS` |
| Worker database role | `NOSUPERUSER`, explicit `BYPASSRLS` |

After this complete regression baseline, two final runtime fixes changed the
generation repository and worker. Their focused regression is `47 passed`,
with Ruff and mypy passing for both files. The complete suites above were not
rerun after those two changes and must not be represented as final-snapshot
full regression evidence.

Runtime evidence:

- [control-plane browser evidence](production-local-demo.json)
- [worker fail-closed evidence](production-local-worker-readiness.json)
- [session restart evidence](production-local-session-restart.json)
- [PostgreSQL and MinIO restore evidence](production-hardening-e9-restore.md)
- [first-login screenshot](screenshots/production-local-first-login.png)
- [model catalog screenshot](screenshots/production-local-models.png)
- [usage screenshot](screenshots/production-local-usage.png)
- [generation history screenshot](screenshots/production-local-generations.png)
- [account/session screenshot](screenshots/production-local-account.png)

The worker runtime drill stopped video and media independently. In each case,
readiness became `503`, the matching HTTP admission returned
`GENERATION_SUBMISSION_DISABLED`, and generation, reservation, idempotency, and
outbox counts did not change. After restart, readiness returned to `200`.

The browser control-plane run performed no paid Provider calls and deliberately
records `availableCards=0`. This is honest disabled-route evidence, not a model
success claim. Live artifacts are stored outside the Git tree so generating
them does not invalidate their source binding.

## Final live-validation update

A signed four-modality Provider smoke subsequently passed on clean commit
`ba76f74980184927eecb151c8c874297594c5441`: text returned non-empty output,
request identity and usage; image, video and audio returned validated artifacts
of 213,470, 2,784,736 and 180,524 bytes respectively. The evidence was bound to
the catalog manifest, smoke-script digest, commit, freshness window and HMAC,
and remains outside Git.

A real full-stack chat smoke also passed on that commit. The following image
acceptance exposed an async ORM response-mapping defect. The repository now
refreshes the database-updated job before mapping it, and focused regression
passes. Post-fix image attempts ended once as `submitted_unknown` and once as a
structured `provider_http_error`; no final current-snapshot image success was
established before handoff.

The public handoff snapshot therefore has no current-commit full-stack Provider
acceptance. The `ba76f749…` evidence is historical, cannot be used to activate
the later snapshot, and does not make the handoff production ready.

## Evidence boundary

- Docker is unavailable on this workstation. Native full-stack behavior and
  standalone contents are verified locally; built-image startup and immutable
  image digests remain a CI/release-host gate. A receipt without them is
  `BOUNDED`, never `PASS`.
- Local staging uses loopback HTTP/AMQP and isolated credentials. External
  production still requires operator-managed TLS endpoints and secrets.
- The internal PTS wallet and ledger are not a completed commercial payment
  channel.
- The customer product scope is incomplete: only one real text route exists,
  and versioned System Prompt management, file context, web citations, platform
  API keys and a real payment channel remain unimplemented.
- Capacity, chaos, customer-specific compliance, and external rollout approval
  are separate release decisions.
