# DECISIONS — Architecture Decision Records

Format: context → decision → consequences → alternatives rejected. New ADRs get
incrementing numbers; superseded ADRs stay with a Superseded-by note.

## ADR-001 — pnpm workspaces, no task orchestrator yet

Context: monorepo with two React apps and shared TS packages.
Decision: pnpm 9 workspaces driven by root `pnpm -r` scripts. No Nx/Turborepo at M0.
Consequences: zero extra tooling; build graph stays simple enough to reason about.
Revisit when inter-package rebuild ordering hurts (expected around M5).
Rejected: Nx (heavy for current size), npm/yarn workspaces (weaker workspace protocol
and lockfile ergonomics).

## ADR-002 — Official pgvector image

Context: need Postgres 16 + pgvector + pg_trgm without maintaining a fork.
Decision: `pgvector/pgvector:pg16` image; extensions enabled via init script.
Consequences: one less Dockerfile to maintain; image provenance is the upstream
project's. Licence note: pgvector is PostgreSQL-licensed, Postgres licence — cleared
for internal commercial use.
Rejected: apt-installing extensions into stock postgres (drift risk).

## ADR-003 — Empty Alembic baseline now, entities from M2

Decision: Alembic async template wired to settings; revision `0001_baseline` is empty.
Consequences: migration plumbing is exercised from day one; down-then-up testing
becomes mandatory once real migrations exist (M2 gate).
Rejected: deferring Alembic entirely (first real migration would then be untested plumbing).

## ADR-004 — Dev host port map

Decision: PG 15432, Redis 16379, MinIO 19000/console 19001, API 18000,
web dev servers 15173/15174.
Consequences: avoids collisions with common local defaults; documented in RUNBOOK.

## ADR-005 — Compose-inlined dev environment

Decision: compose.yaml carries development-only env values inline so `docker compose up`
is a single command with no `.env` step. Production config arrives exclusively via
Helm/env (M12); no secrets ever in the repo.
Consequences: `.env` remains optional for local non-Docker runs against published ports.
Rejected: env_file indirection in dev (extra manual step violates the §13 one-command bar).

## ADR-006 — Egress scan scope and allowlist mechanics

Context: hard constraint 1.5 requires CI-level enforcement, not good intentions.
Decision: `scripts/check_no_egress.sh` scans every git-tracked text file for
scheme-bearing URLs. Excluded from scanning: package-lockfiles (registry URLs are
build-time), all Markdown (prose legitimately cites external systems), the scanner
itself, and the allowlist file. Exceptions live in `infra/egress_allowlist.txt` as
`path-glob::line-regex` rules and may only reference loopback or internal service
hosts. ESLint additionally bans absolute-URL literals/template segments in frontend
source at AST level.
Consequences: docs can discuss URLs freely while executable surface stays clean;
negative test (planted URL) is part of milestone verification.
Rejected: allowing docs in-scope (unreviewable churn), URL-scoped-only allowlisting
(paths matter for review).

## ADR-007 — Frontend dependencies land on first use

Decision: M0 ships react/react-dom/vite/typescript/eslint only. TanStack Query,
Zustand, RHF+Zod, router, CodeMirror, LiveKit client arrive in the milestone that
first consumes them.
Consequences: smaller audit surface (`npm audit`, §13) and honest lockfiles.
Rejected: installing the full locked stack upfront (dead weight until used).

## ADR-008 — MinIO server-side encryption deferred to production wiring

Context: constraint requires SSE on buckets.
Decision: dev compose runs single-node MinIO with a pinned release and bucket-init;
SSE-S3 via KES + org KMS/Vault is wired in the Helm/prod milestone (M12) where real
key management exists. Recorded here as an explicit, temporary gap rather than a
silent omission.
Consequences: dev artefacts are unencrypted at rest inside the dev VM only.

## ADR-009 — CSP enforcement points

Decision: FastAPI middleware emits the exact mandated CSP from day one (tested).
The SPA-serving layer adds equivalent headers when static hosting lands (M5);
Vite dev-server is exempt because HMR requires inline scripts — enforced CSP applies
to built output only.
Rejected: shipping CSP only at "hardening time" (retrofitting headers onto features
is how CSP becomes decorative).

## ADR-010 — Readiness probes fail soft per dependency

Decision: each readyz check runs under a timeout guard returning per-dependency
status; MinIO probes use a dedicated urllib3 pool with retries disabled so degraded
deps yield a fast, structured 503 instead of hanging requests or a 500.
Consequences: orchestrators see deterministic readiness semantics; offline unit tests
are stable without services running.

## ADR-011 — The only two type-ignore sites

Decision: `Settings()` construction (env-populated required fields defeat constructor
typing) and `redis.asyncio.from_url` (upstream ships it untyped) carry inline
justified ignores. Everything else must pass `mypy --strict` / `no-explicit-any`.
Consequences: any new ignore needs a justification comment plus a DECISIONS entry.

## ADR-012 — Reserved service directories, prose ownership split

Decision: `services/*` and `packages/ui` exist as placeholders (.gitkeep/package.json)
until their milestones; no stub code pretending to work. README.md and
CLIENT_DOCUMENTATION.md are authored by a parallel documentation agent based on the
code; this repo's engineering docs are PLAN/DECISIONS/RUNBOOK/MODEL_CARD.
Consequences: no fake implementations; doc drift owned explicitly.

## ADR-013 — Readiness polling instead of `compose up --wait`

Context: the MinIO bucket-init service is a legitimate one-shot container that exits 0
on success. `docker compose up --wait` reports any exited container as a failure, so a
fully healthy stack returns non-zero — proven in CI.
Decision: `docker compose up -d` followed by `scripts/wait_ready.sh`, which polls
`/readyz` until all dependencies (including the bucket) report up, with a timeout and
diagnostics on failure. CI integration job uses the same script, so gate semantics are
identical locally and in CI.
Consequences: one extra command; readiness truth lives in the API rather than
container heuristics.
Rejected: dropping bucket-init into the API entrypoint (mixes infra concerns into app
boot), `restart: always` on init (masks real failures).

