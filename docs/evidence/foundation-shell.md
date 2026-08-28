# Foundation and Product Shell Evidence

Observed in the isolated `mosaic-foundation-shell` worktree on 2026-08-21.

- Design status: `demo_scaffolding`
- Server-side authorization: NOT_IMPLEMENTED_SCOPE
- Provider status: `provider_unverified`
- Web lint: PASS (`pnpm verify:web`)
- Web typecheck: PASS (`pnpm verify:web`)
- Contracts tests: PASS (8 tests)
- Design-token drift: PASS
- Web unit tests: PASS (65 tests)
- Next build: PASS
- API pytest: PASS (15 tests)
- Alembic heads: PASS (`20260820_0001 (head)`)
- Ruff: PASS
- mypy: PASS (11 source files)
- Playwright desktop: PASS (7 tests)
- Playwright wide: PASS (7 tests)
- Playwright mobile: PASS (7 tests)
- axe serious/critical: PASS (0 violations across `/`, `/login`, and signed-in `/models` in all three projects)
- Browser to API live path: PASS (real browser same-origin fetch through the Next rewrite; HTTP 200, exact `mosaic-api` live payload)
- Browser to API unavailable-ready path: PASS (real browser same-origin fetch through the Next rewrite; HTTP 503, error code `DATABASE_NOT_READY` with `DATABASE_URL` pinned to closed loopback port 1)
- Real PostgreSQL readiness: NOT_RUN_ENVIRONMENT

The browser evidence proves the foundation shell, client-side demo route gating, responsive navigation, accessibility threshold, and the Next rewrite to the FastAPI live/unavailable-ready endpoints. It does not prove server-side authorization, real authentication, protected data, model invocation or provider availability, job execution, asset storage, billing, or data-center deployment/operations.

The browser run uses dedicated configurable loopback ports (defaults `3100`/`8100`), starts fresh production web/API processes with server reuse disabled, and pins the API `DATABASE_URL` to closed loopback port 1 for deterministic unavailable-readiness evidence. This does not claim production deployment readiness.
