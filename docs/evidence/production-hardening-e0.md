# Production Hardening E0 Baseline Receipt

Date: 2026-08-26
Branch: `codex/production-hardening`
Baseline commit: `a91454acdfd221fbf3e224b5d7ab6d37aef4b5a0`

## Source boundary

- Created from committed `codex/bailian-workspace-redesign@a9f64bb`.
- Added the root GStack routing commit as `a91454a`.
- The dirty `product-production-backend` worktree and the dirty `main` worktree were not modified or imported.
- No production deployment or live Provider call was performed.

## Dependency identity

- Node: `v24.14.0`
- pnpm: `11.19.0`
- uv: `0.11.28`
- `pnpm-lock.yaml` SHA-256: `A71FBE96DFCAAB39ACD14CF9F73ACDA9454A926F6AEED4474F19F8E94093158C`
- `apps/api/uv.lock` SHA-256: `9BA9CB36A7AAF9606E8213C5CDCFC770EFA4952028901E45E607D3346708114B`

## Fresh gates

| Gate | Result |
|---|---|
| Web lint/typecheck/boundaries | PASS |
| Contracts | 52 passed |
| Design tokens | 4 passed |
| Web unit/component | 263 passed |
| Next.js production build | PASS |
| API pytest | 210 passed, 5 skipped |
| Ruff | PASS |
| strict mypy | PASS, 103 source files |
| Alembic | one head, `20260825_0007` |

## Explicit non-passes

- The PostgreSQL billing concurrency test is a skip-only placeholder.
- Four live Provider tests require an explicit authorized environment.
- The normal browser suite defaults to Demo mode.
- Load, chaos, backup/restore and release rollback are not covered by this receipt.

## E0 verdict

`PASS` for a clean, reproducible implementation baseline.
`NOT PRODUCTION ACCEPTED`; Gates E1 through E10 remain required.
