# Phase 3 production foundation checkpoint

Date: 2026-08-24

Branch: `codex/product-production-backend`

Status: `SUPERSEDED HISTORICAL CHECKPOINT`

This file records the first Phase 3 checkpoint, when the persistent schemas,
authentication, billing primitives and Provider protocol adapters existed but
the real local infrastructure and execution workers had not yet passed.

The branch later added and verified those verticals. Use these records for the
current state:

- `phase3-provider-live.md` — real Bailian four-modal gate.
- `phase3-durable-chat.md` — queue-backed real chat vertical.
- `phase3-successful-demo.md` — browser, media, usage and current boundaries.

## Foundation delivered at this checkpoint

- Native multi-tenant registration/login/session boundaries with Argon2id,
  opaque token hashes, CSRF protection and Redis login admission.
- PostgreSQL/Alembic models for tenants, users, memberships, sessions, catalog,
  entitlements, conversations, generations, usage, wallets, reservations,
  immutable ledger entries and outbox events.
- Integer-minor-unit billing primitives with row locks, idempotent reserve,
  capture and release operations, plus an append-only ledger trigger.
- Bailian adapters for text, image, asynchronous video and speech synthesis.
- Tenant-scoped durable generation acceptance with canonical idempotency and a
  public projection that omits Provider and storage internals.
- API mode as the frontend default, with Demo mode kept explicit and isolated.

The earlier blocked assertions are intentionally not retained as current facts;
the later evidence files show the actual live acceptance and remaining
production gaps.
