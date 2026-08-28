# Phase 3 durable chat vertical evidence

Date: 2026-08-24

Branch: `codex/product-production-backend`

## Outcome

The durable chat vertical is implemented and passed a real
browser-to-Bailian run. The previous snapshot in this file, which described the
worker as disabled and PostgreSQL/RabbitMQ as unavailable, is superseded by the
live evidence in `phase3-successful-demo.md`.

## Implemented path

- Tenant-scoped registration, login, opaque sessions and CSRF protection.
- Conversation/message/request state, replayable SSE events and active-request
  exclusivity in PostgreSQL.
- A single acceptance transaction writes the user message, assistant placeholder,
  queued request, first event and fenced outbox event.
- Fenced outbox claim/renew/mark operations prevent a stale relay owner from
  mutating a newer claim.
- RabbitMQ publisher confirms, persistent identifier-only messages, quorum work
  queue and dead-letter queue.
- Idempotent consumer validation against the authoritative outbox and request
  rows.
- Leased worker execution, real Bailian streaming, short durable delta writes,
  stop handling, usage recording and billing settlement.
- Expired lease recovery moves ambiguous in-flight requests to
  `submitted_unknown` rather than automatically repeating a potentially
  chargeable Provider call.
- Billing reconciliation repairs terminal request/reservation drift.
- Redis worker heartbeat is set only after Provider and RabbitMQ initialization;
  compare-and-delete cleanup avoids an old process deleting a new heartbeat.
- The readiness endpoint rejects chat submissions unless the complete stack is
  enabled and a live worker heartbeat exists.

## Live acceptance

- Real model: `qwen3.5-plus`.
- Real conversation:
  `efb5c4a2-170a-4808-ad61-0c00b5ffd8d2`.
- Browser-created conversation:
  `cbebe3c8-81e1-46b6-9e69-98a7de429640`.
- PostgreSQL showed terminal `succeeded`, contiguous event sequences, Provider
  request identity, usage and settled promotional billing.
- The corresponding outbox row was published and the live quorum queue returned
  to zero ready/unacknowledged messages.
- Refreshing the browser reconstructed the conversation from the API rather than
  from demo state.

## Remaining scale boundary

Current SSE delivery uses bounded PostgreSQL polling. External high-concurrency
acceptance still requires Redis/notification fan-out, connection backpressure,
stream metrics and load tests. Conversation listing/history also needs stable
cursor pagination and retention policy before large tenant datasets are
accepted.
