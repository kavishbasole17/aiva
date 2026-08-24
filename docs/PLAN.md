# PLAN — Milestone 0: Foundation & Air-Gap Skeleton

Status: **delivered, awaiting gate proof** (see bottom of file).

## Goal

Monorepo scaffold, dev infrastructure via Docker Compose, CI skeleton, egress
enforcement, and the governance documents that constrain every later milestone.
Gate: `docker compose up` all services healthy; CI green on GitHub Actions.

## Deliverables

1. Monorepo layout per the locked stack: `apps/{api,web-recruiter,web-candidate}`,
   `services/{ai-gateway,worker,sandbox-runner}` (reserved), `packages/{ui,contracts,eval}`,
   `infra/`, `scripts/`, `docs/`, `.github/workflows/`.
2. Compose dev stack: Postgres 16 + pgvector + pg_trgm, Redis 7 (AOF), MinIO
   (pinned server + pinned mc bucket-init one-shot), API container with healthcheck.
3. API skeleton: `/healthz` liveness, `/readyz` probing Postgres / Redis / MinIO,
   pydantic-settings fail-closed config, structured JSON logging, strict CSP +
   security-header middleware. Unit tests run offline with deterministic dead-port
   settings; integration tests gated behind `AIVA_INTEGRATION=1`.
4. Web shells: React 18 + TS 5 (`strict`, `noUncheckedIndexedAccess`,
   `exactOptionalPropertyTypes`), ESLint type-checked ruleset banning `any` and
   absolute-URL string/template literals in source.
5. Egress enforcement: `scripts/check_no_egress.sh` (deny-by-default,
   allowlist-reviewed exceptions for loopback/internal references only) wired into CI.
6. CI: egress scan, compose validation, web lint/typecheck/build, API
   ruff/black/mypy-strict/bandit, unit tests, live-stack integration job.
7. Governance docs: this plan, DECISIONS.md, RUNBOOK.md, MODEL_CARD.md.

## Verification evidence

| Gate item | Status |
|---|---|
| `pnpm -r lint` | passed locally (both apps + contracts) |
| `pnpm -r typecheck` / `build` | passed locally |
| `ruff check apps/api` | passed locally |
| `black --check apps/api` | passed locally |
| `mypy --strict apps/api/app` | passed locally |
| `pytest` unit suite | 10 passed, 2 integration-skipped locally |
| `bandit -c pyproject.toml -r app` | 0 issues |
| `scripts/check_no_egress.sh` positive | pass, 49 files scanned |
| `scripts/check_no_egress.sh` negative | planted external URL → exit 1 (verified, then removed) |
| `docker compose up --wait` healthy | pending local Docker install (WSL); proven in CI integration job |
| GitHub Actions green | checked after push |

## Deliberately deferred

Auth/RBAC, DB entities beyond the empty Alembic baseline, design tokens and all
visual work (atigro.com colour sampling precedes M1), AI models and ai-gateway,
LiveKit, sandbox runner internals, coverage thresholds, golden-set harness content.
