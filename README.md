# AIVA

Air-gapped AI candidate evaluation and interview automation. On-premise, zero external
runtime network calls, every model served locally.

## Status

Milestone 0 — Foundation & Air-Gap Skeleton. Per `docs/PLAN.md`, this milestone is
marked "delivered, awaiting gate proof" (i.e. implementation complete, formal
verification against the gate criteria in progress). Governance docs now exist:
`docs/PLAN.md` (build order and verification evidence), `docs/DECISIONS.md`
(architecture decision records), `docs/RUNBOOK.md` (day-2 operations), and
`docs/MODEL_CARD.md` (AI model inventory, empty until Milestone 3).

## Repository layout

```
apps/
  api/               FastAPI service (health, readiness, security headers)
  web-recruiter/     Recruiter console (React 18, TS strict)
  web-candidate/     Candidate journey + interview runner
services/
  ai-gateway/        Single entry to all local models (Milestone 3)
  worker/            ARQ jobs: parsing, scoring, transcription, reports
  sandbox-runner/    Isolated code execution (Milestone 9)
packages/
  ui/                Design system, tokens, motion primitives (Milestone 1)
  contracts/         Zod schemas + generated TS types from OpenAPI
  eval/              Golden-set evaluation harness
infra/               Postgres init, egress allowlist, future Helm/policies
scripts/             Enforcement tooling
docs/                PLAN, DECISIONS, RUNBOOK, MODEL_CARD
```

## Prerequisites

- Docker + Docker Compose (v2, `compose.yaml` uses the `docker compose` CLI)
- Node.js >= 22
- pnpm 9.15.0 (pinned via `packageManager` in `package.json`)
- Python 3.11.x (pinned via `apps/api/pyproject.toml`, `>=3.11,<3.12`)

## Quickstart

```bash
cp .env.example .env      # then adjust values as needed
pnpm install               # installs workspace packages once apps/packages exist
docker compose up -d
scripts/wait_ready.sh
curl http://localhost:18000/readyz
```

Services: Postgres 16 + pgvector on 15432, Redis 7 on 16379, MinIO on 19000 (console
19001), API on 18000, plus a one-shot `minio-init` job that creates the
`aiva-artifacts` bucket automatically so `/readyz`'s MinIO check passes without
manual setup. All ports are non-default host mappings to avoid clashing with other
local services.

## API service (`apps/api`)

Python 3.11, FastAPI. Dependencies and tooling are defined in `apps/api/pyproject.toml`:

- **Runtime**: FastAPI, uvicorn, pydantic-settings, structlog, SQLAlchemy (async) +
  asyncpg, redis, minio, alembic (migrations), argon2-cffi (password hashing),
  pyjwt (JWT tokens), pyotp (TOTP two-factor authentication) — the latter three
  were just added; no authentication code exists yet, but this signals the
  intended approach: password hashing with Argon2, JWT-based sessions, and
  built-in two-factor auth support
- **Dev/quality**: pytest + pytest-asyncio + httpx (tests), ruff + black (lint/format),
  mypy in strict mode (type checking), bandit (security static analysis)

Modules so far:

- `settings.py` — validated `Settings` reading all `AIVA_*` env vars
- `health.py` — `GET /healthz` (liveness) and `GET /readyz` (readiness; checks
  Postgres, Redis, MinIO with a 2s timeout each)
- `logging_setup.py` — structured JSON logging via `structlog`
- `security_headers.py` — CSP + security-headers middleware (`SecurityHeadersMiddleware`)
- `main.py` — `create_app()` FastAPI factory; wires settings, dependency lifecycle
  (Postgres/Redis/MinIO clients opened on startup, closed on shutdown), logging, the
  security-headers middleware, and the health router. Interactive API docs
  (`/docs`, `/redoc`) are intentionally disabled — only the raw `/openapi.json` schema
  is exposed — since Swagger/ReDoc UIs normally load JS/CSS from a CDN, which the
  air-gap policy forbids. The app instance is importable as `app.main:app`.

Data model: `app/models.py` defines the first real entities (SQLAlchemy 2.0
declarative, async) — `Organization`, `Department`, `User` (with `role`,
`password_hash`, and `mfa_secret`/`mfa_enabled` fields), `Requisition` (a job
opening, with `draft`/`open`/`closed` status and an optimistic-locking
`version` column), `RefreshToken`, and `AuditEvent`. A `Role` enum defines six
roles: `admin`, `hiring_manager`, `recruiter`, `interviewer`, `auditor`,
`candidate`.

- `app/db.py` — async session factory, plus `bind_rls_context()`, which sets
  Postgres session variables (`aiva.organization_id`, `aiva.user_id`,
  `aiva.role`) via `set_config` for **Postgres Row-Level Security**-based
  multi-tenant data isolation (the actual RLS policies are not yet visible in
  a migration).
- `app/audit.py` — a tamper-evident audit log: each `AuditEvent` stores a
  SHA-256 hash of its own canonicalized content chained to the previous
  event's hash (`prev_hash`/`entry_hash`), and `verify_chain()` checks that
  chain end-to-end. Any retroactive edit to a past event breaks the chain.
- `RefreshToken` implements rotation-with-reuse-detection: each token belongs
  to a `family_id`; `is_live()`/`is_reused()` distinguish a valid token from
  one replayed after rotation, a standard defense against stolen refresh
  tokens.

Migration `0002_core_entities_rls` now creates all six tables and enforces
real database-level security, not just application-level checks:

- A `CHECK` constraint restricts `users.role` to the six defined roles at the
  database layer (defense in depth beyond the application's own validation).
- Row-Level Security is enabled and **forced** (`FORCE ROW LEVEL SECURITY`,
  meaning even the table owner cannot bypass it) on `departments`, `users`,
  and `requisitions`, each with explicit select/insert/update/delete policies
  scoped to the organization set in the session via `bind_rls_context()`. A
  narrow bootstrap exception allows access when no organization context is
  set yet (e.g. during initial signup).
- A dedicated, minimally-privileged database role (`aiva_app`) is granted
  exactly the access the application needs — the API does not connect as a
  database superuser.

This means the previously-described data model and RLS design are now real
and enforced, not just planned. The privilege separation is now fully wired
end to end: `infra/postgres/initdb/01_extensions.sql` creates the `aiva_app`
login role; `AIVA_DATABASE_URL` (used by the running API) connects as
`aiva_app`, while a new `AIVA_ADMIN_DATABASE_URL` setting (used only by
Alembic, via `alembic/env.py`) connects as the superuser to run migrations —
so the application itself never holds elevated database privileges.

`app/routers_org.py` also gained `POST /orgs/{id}/users` (admin-only): lets an
organization admin directly create a staff account (recruiter, interviewer,
auditor, or hiring manager) with a set password and role, as distinct from
the self-service `/auth/register-org` signup flow. It rejects duplicate
emails and refuses to create a `candidate`-role account through this
staff-only endpoint.

Authentication service: `app/auth_service.py` and `app/deps.py` implement a
full auth backend, though no HTTP endpoints (login/register/refresh) expose it
yet:

- Password hashing via Argon2 (`hash_password`/`verify_password`)
- TOTP-based MFA: secret generation, an authenticator-app provisioning URI, and
  time-window-tolerant verification
- JWT access tokens (`issue_access_token`/`decode_access_token`, HS256,
  configurable lifetime, default 15 minutes) and opaque refresh tokens, stored
  only as a SHA-256 digest (`mint_session`)
- Refresh token rotation with reuse detection (`rotate_refresh_token`): each
  rotation invalidates the previous token; if an already-rotated token is
  presented again, the entire token family is revoked and the attempt is
  treated as a compromise signal
- `deps.py` provides FastAPI dependencies for optional/required authentication
  (`get_optional_user`/`require_user`), role-based access control
  (`require_roles(*allowed)`), and a `get_db` dependency that binds the
  Row-Level-Security context (via `bind_rls_context`) for every authenticated
  request before yielding a database session
- New settings: `jwt_secret` (min. 24 characters, validated), `admin_database_url`
  (optional, presumably for privileged/RLS-bypassing operations),
  `access_token_minutes`, `refresh_token_days`

`app/routers_auth.py` exposes the corresponding HTTP endpoints:
`POST /auth/register-org` (self-service organization + admin-user signup),
`POST /auth/login` (email/password, with TOTP required once MFA is enabled),
`POST /auth/refresh` (rotates a refresh token), `POST /auth/mfa/enroll` and
`POST /auth/mfa/activate` (role-restricted to admin/hiring manager/recruiter),
and `GET /me`. Every auth-relevant action writes an `AuditEvent`. `main.py`
now registers this router (plus `routers_org` and `routers_audit`, below) and
wires up `app.state.session_factory` in the app lifespan, so these endpoints
are reachable through the running API, with all underlying tables and RLS
policies now present in the database migration (see below) — though still
untested end-to-end against a live database as far as the repo shows.

`app/routers_org.py` — the first real business-domain API, scoped to the
authenticated user's organization throughout: `GET /orgs/{id}`,
`POST /orgs/{id}/departments`, `GET /departments/{id}`,
`POST /departments/{id}/requisitions`, `GET /requisitions/{id}`,
`PATCH /requisitions/{id}` (optimistic-locked via the `version` column), and
`DELETE /requisitions/{id}`. Access is role-gated per endpoint (e.g. only
admins can create departments or delete requisitions), cross-organization
access is explicitly rejected, and every mutation writes an `AuditEvent`.

`app/routers_audit.py` — `GET /audit-events` (paginated, org-scoped, admin/
auditor only) and `GET /audit-events/verify`, which runs `verify_chain()`
against the full event history and reports whether the hash chain is intact.

Containerization: `apps/api/Dockerfile` is a multi-stage build (builder → slim
runtime), runs as a non-root `aiva` user, and accepts a `PIP_INDEX_URL` build arg so
images can be built against an internal/offline PyPI mirror instead of the public
internet — consistent with the air-gap policy. `docker compose up -d` followed by
`scripts/wait_ready.sh` now builds and runs the full stack end-to-end (plain
`docker compose up --wait` is deliberately not used — see ADR-013 below).

Tests: `apps/api/tests/` (pytest, httpx, `asgi-lifespan`) covers `/healthz`, 404
handling, honest `503`/`degraded` reporting on `/readyz`, config validation
(required env vars fail closed, invalid values rejected), and security headers
(present on both success and error responses, CSP matches spec exactly). Tests run
against unreachable dependency addresses by default (fast, no Docker needed); set
`AIVA_INTEGRATION=1` to run against the real Postgres/Redis/MinIO stack instead.
`test_audit.py` verifies the tamper-evident hash chain (detects a tampered
payload and a broken link, confirms hashing is stable), and
`test_auth_unit.py` covers password hashing, JWT issuance/expiry/tampering
rejection, refresh-token uniqueness, and TOTP verification.

`test_integration_auth.py` (requires `AIVA_INTEGRATION=1` + the live stack)
proves the authorization design end-to-end: a full role-permission matrix for
a recruiter account (200/201/403 as expected per endpoint), cross-organization
access returning 404 rather than 403 (so a user can't tell whether a resource
in another org even exists), refresh-token rotation with reuse correctly
revoking the whole token family, the audit chain reporting intact via the API
after real activity, and the complete MFA enroll → activate → login flow
(including that password-only login is rejected once MFA is active). **Not
yet wired into CI**: `.github/workflows/ci.yml`'s `integration` job now runs
`alembic upgrade head` against the live stack, but still only executes
`test_integration_readiness.py`, not `test_integration_auth.py` — so this
thorough new coverage exists but is not yet part of the automated gate.

## Design system (`packages/ui`) — Milestone 1

Work has started here. `tsconfig.json` (strict, `noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`) is in place, plus two CSS files that define the
visual foundation:

- `tokens.css` — CSS custom properties for fluid typography (`clamp()`-based
  type scale), spacing, corner radii, and motion (durations/easing), with a
  `prefers-reduced-motion` override. Color is defined as a dark-first theme
  (`:root[data-theme="dark"]`) with a parallel light theme
  (`:root[data-theme="light"]`), both toggled via a `data-theme` attribute.
- `fonts.css` — Space Grotesk (display), Inter (body), and JetBrains Mono
  (data/monospace), imported from `@fontsource-variable` npm packages rather
  than a font CDN — consistent with the air-gap policy — though these
  dependencies are not yet declared in `packages/ui/package.json`.

Components so far:

- `theme-storage.ts` + `theme.tsx` — persisted dark/light theme toggle:
  `ThemeProvider`/`useTheme` (React context) plus `loadTheme`/`applyTheme`/
  `saveTheme` helpers that read/write `localStorage` (`aiva.theme`) and set
  the `data-theme` attribute `tokens.css` keys off of. Defaults to dark.
- `motion-tokens.ts` + `hooks.ts` — shared animation constants (spring physics,
  durations, easing curves) and two hooks: `usePrefersReducedMotion` and
  `useOneShotIntersection` (fires once when an element scrolls into view).
- `Reveal.tsx` — `Reveal` (fade/slide-in-on-scroll wrapper) and `PageStagger`
  (staggers a list of children into view), both built on the `motion` library
  and skipping the animation entirely when reduced motion is requested.
- `ScoreRing.tsx` — the first domain-specific component: an animated,
  accessible circular score/progress indicator (spring-animated arc, proper
  `role="meter"` and `aria-value*` attributes), evidently intended for
  displaying candidate evaluation scores in the recruiter console.

A first component library also landed, styled with Tailwind CSS utility
classes bound to the design tokens above via `tailwind.preset.js` (colors,
fonts, and transition durations all resolve to the CSS custom properties;
dark mode keys off `[data-theme="dark"]`):

- `Button` (4 variants: primary, action, ghost, danger), `Field` (label + hint
  + error wrapper), `Input`, `Textarea`, `Card` (with an interactive/hover
  state), `Badge` (5 semantic tones), `EmptyState`, and `Skeleton` (loading
  placeholder, disabled under reduced motion).

The package (`@aiva/ui`, now versioned `0.1.0`) has a real dependency list
(`@fontsource-variable/*` fonts, `motion`), React as a peer dependency, and a
proper export map (`.`, `./tokens.css`, `./fonts.css`, `./tailwind.preset`) —
Both `apps/web-recruiter` and `apps/web-candidate` have now adopted it:
Tailwind + PostCSS configured with the shared preset, and
`@aiva/ui/tokens.css` + `@aiva/ui/fonts.css` imported in each `main.tsx`. No
real page layouts or forms have been assembled from these pieces yet — both
apps currently show milestone-checkpoint screens, not real functionality.

## Package/service scaffolding

The remaining monorepo locations named in "Repository layout" above still exist
as empty stubs, with no functionality yet:

- `packages/contracts`, `packages/eval` — each has only a
  `package.json`/`pyproject.toml` and, where applicable, a single placeholder
  export or module.
- `services/ai-gateway`, `services/worker`, `services/sandbox-runner` — empty
  directories (`.gitkeep` only), reserved but not started.

## AI gateway (`services/ai-gateway`) — Milestone 3

A standalone FastAPI service (own `pyproject.toml`, same quality tooling as
`apps/api`: ruff, black, mypy strict, bandit, pytest), configured via
`AIVA_GATEWAY_*` env vars (`llm_backend`, defaulting to `mock`;
`vllm_base_url`; `vllm_model`, defaulting to `Qwen2.5-14B-Instruct-AWQ`, the
model recorded in `docs/MODEL_CARD.md`).

- `app/contracts.py` — the gateway's stable response contract. `JudgementBase`
  requires `rationale`, `confidence` (0–1), and `cited_span_ids` (at least
  one) on every judgement; `DimensionScore` and `ResumeFieldExtraction`
  extend it. This is a hard constraint (referenced in-code as "constraint
  8.1"): **no AI output can exist without evidence it can be traced back
  to** — this is the foundation for the "Evidence Spine" referenced in the
  Milestone 5 roadmap entry.
- `app/prompts.py` (`PromptRegistry`) — loads `.txt` prompt templates from
  `services/ai-gateway/prompts/`, does simple `{{variable}}` substitution, and
  computes a content-hash `version` for each prompt so every generation can
  record exactly which prompt version produced it.
- `prompts/dimension_score.txt` — the first real prompt, for scoring one
  evaluation dimension against a job description. It explicitly instructs the
  model: score only what the candidate's own documents/statements support,
  cite at least one evidence span id, and never infer emotion, personality,
  or confidence — a deliberate anti-hallucination/anti-bias guardrail baked
  into the prompt itself.
- `app/backends.py` — a pluggable `Backend` interface with two
  implementations: `MockBackend` (deterministic, hash-seeded fake data that
  still validates against the real response schema — lets the rest of the
  system be built and tested before real models/hardware exist) and
  `VllmBackend` (calls a real vLLM OpenAI-compatible endpoint using
  **guided/constrained decoding** — passing the Pydantic JSON schema as
  `guided_json` — with `temperature=0` and a deterministic seed for
  reproducibility; validates the model's response against the same schema and
  raises a clear error if the model breaks contract). `GenerationResult`
  records the `prompt_version`, `backend`, and `model_id` alongside every
  generated result, giving full provenance for any AI output.

`app/main.py` assembles a real, running FastAPI app (`create_app()`, same
`docs_url=None`/`openapi_url="/openapi.json"` pattern as `apps/api`) exposing:

- `GET /healthz`
- `GET /prompts` — lists every loaded prompt with its content-hash version
- `POST /v1/generate` — the core endpoint: given a `prompt_id`, a
  `response_model` name, template `inputs`, and a `seed_key`, it renders the
  prompt, runs it through the configured backend (mock or vLLM), validates
  the result against the response contract, and returns the data plus its
  `prompt_version`/`backend`/`model_id` provenance. Missing template inputs,
  an unknown prompt, or an unknown response model all return clear 400/404
  errors rather than failing silently.

`apps/api/tests/test_gateway.py`-equivalent tests (in
`services/ai-gateway/tests/`) prove the mock backend is genuinely
deterministic: the same request repeated returns byte-identical output, and
changing an input (e.g. the dimension being scored) changes the output
accordingly.

Not yet done: no `Dockerfile`, and this service is not wired into
`compose.yaml` or called by the main API yet — it runs and is tested in
isolation but isn't part of the integrated stack.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request, as
independent jobs:

- `no-egress` — runs `scripts/check_no_egress.sh` against the full checkout
- `compose-config` — validates `compose.yaml` with `docker compose config -q`
- `web` — pnpm install, lint, typecheck, and build across all frontend workspaces
- `api-quality` — ruff, black `--check`, mypy (strict), and bandit against `apps/api`
- `api-tests` — runs the API's offline unit test suite
- `integration` — boots the full `docker compose` stack and runs
  `test_integration_readiness.py` against the live services (`AIVA_INTEGRATION=1`),
  then tears the stack down

## Architecture decisions (selected)

Full rationale in `docs/DECISIONS.md` (12 ADRs as of this update). Notable ones:

- pnpm workspaces only at M0, no Nx/Turborepo yet (revisit around M5)
- Official `pgvector/pgvector:pg16` image; PostgreSQL-licensed, cleared for
  internal commercial use
- Dev secrets are inlined in `compose.yaml` for a true one-command `docker
  compose up`; production config arrives exclusively via Helm/environment at a
  later infrastructure milestone (M12) — no secrets ever committed to the repo
- MinIO server-side encryption at rest is explicitly deferred to the production
  milestone (M12), where real key management (KES + org KMS/Vault) exists; this
  is a recorded, deliberate dev-only gap, not a silent omission
- Frontend dependencies (including the LiveKit client for future live
  interviews) are added only in the milestone that first uses them, to keep the
  dependency audit surface honest
- Every `mypy` type-ignore in the codebase carries an inline justification; any
  new one requires a matching DECISIONS entry
- `docker compose up --wait` is deliberately avoided: MinIO's one-shot
  bucket-init container exits 0 on success, but `--wait` treats any exited
  container as a failure. Instead, `docker compose up -d` followed by
  `scripts/wait_ready.sh` (which polls `/readyz`) is used both locally and in
  CI, so readiness truth comes from the API rather than a container heuristic
  (ADR-013)
- The design system's brand color (`--signal`) is not arbitrary: it was
  sampled directly from a reference site's live CSS (primary blue `#1863DC`,
  darker variant `#046BB3`) per a project style requirement, with a separate,
  brighter derived color (`--signal-text`) added specifically so small
  colored text still meets accessibility contrast guidelines (ADR-014)
- `exactOptionalPropertyTypes` was deliberately dropped from all frontend
  TypeScript configs after the `motion` animation library's types proved
  incompatible with it; every other strict-mode flag remains (ADR-015)
- Self-hosted fonts (Space Grotesk, Inter, JetBrains Mono) are all SIL Open
  Font License 1.1, explicitly cleared for commercial use (ADR-016)
- This README and `CLIENT_DOCUMENTATION.md` are explicitly maintained as a
  documentation layer derived from the code, separate from the engineering docs
  (`PLAN`/`DECISIONS`/`RUNBOOK`/`MODEL_CARD`)

## Operations

See `docs/RUNBOOK.md` for the living operational reference: service port table,
configuration, the egress-policy self-test procedure, the full local quality-gate
command sequence, and explicitly marked pending sections (model operations,
backup/restore, incident response — all pending Milestone 12).

## Planned AI capabilities

No AI models are wired up yet (Milestone 0 has none). `docs/MODEL_CARD.md` records
the candidate model for each planned capability, to be finalized as each lands:

| Capability | Candidate model | Milestone |
|---|---|---|
| LLM reasoning/scoring | Qwen2.5-14B-Instruct AWQ (fallback Llama-3.1-8B-Instruct) | M3 |
| Embeddings | bge-m3 (1024-dim) | M3 |
| Resume parsing (NER) | spaCy pipeline | M4 |
| OCR fallback | PaddleOCR / Tesseract | M4 |
| Speech-to-text | faster-whisper large-v3 / distil-large-v3 | M8 |
| Text-to-speech | Piper (ONNX voices) | M8 |
| Identity verification | InsightFace ArcFace (with consent gate) | M8 |
| Proctoring signals | MediaPipe Face Mesh | M8 |
| Reranker | bge-reranker-v2-m3 | M10 |

Licensing rule: Apache-2.0/MIT preferred; anything under a bespoke community
license is flagged for human legal review before integration.

## Full roadmap (per docs/PLAN.md)

`docs/PLAN.md` was restructured into a status ledger. Milestones 0–2 are
listed as "Delivered and CI-verified." **Note on that claim**: for Milestone
2 specifically, PLAN.md states the full authorization matrix, refresh-replay
revocation, MFA flow, and chain integrity are "proven in CI integration job"
— but as of this update, `.github/workflows/ci.yml`'s `integration` job still
only runs `tests/test_integration_readiness.py`, not `test_integration_auth.py`
(see above). This README defers to the directly-observed CI config over the
planning document's claim; treat Milestone 2's CI verification status as
unconfirmed until the workflow file itself runs that test.

Remaining milestones and their dependencies:

| # | Milestone | Depends on |
|---|---|---|
| M3 | AI gateway, local models, constrained decoding, eval harness scaffold | GPU hosts, model weights in image |
| M4 | Resume ingest/parsing, job-description processing, matching, scoring, shortlisting | M2, M3 |
| M5 | Recruiter console: pipeline board, candidate detail, "Evidence Spine" v1 | M1, M4 |
| M6 | Questionnaire builder, candidate portal, evaluation | M4 |
| M7 | Scheduling, availability rules, .ics calendar files, SMTP reminders | M6 |
| M8 | LiveKit pre-check/consent, STT/TTS adaptive interview loop, live HUD | M7 |
| M9 | Sandbox runner, code editor, whiteboard, screen share, task discussion | M8 |
| M10 | RAG-based FAQ, evaluation engine, report generation (PDF/Excel export) | M9 |
| M11 | Dashboard, blind screening, bias audit, integrity signals, DSAR tooling | M10 |
| M12 | Load testing, penetration-test pass, data-retention jobs, Helm chart | M11 |

Open items carried forward in PLAN.md: local Docker Engine install on the
developer's WSL machine is still pending (the compose stack is currently only
proven via the CI integration job, not locally); test-coverage thresholds and
golden-set evaluation content begin at M4; MinIO encryption-at-rest is wired
at M12 (see ADR-008 above). M12's Helm chart also confirms the intended
production deployment target is Kubernetes.

## Milestone 0 verification evidence

Per `docs/PLAN.md`, the following checks have passed locally as of this update:
`pnpm -r lint`, `pnpm -r typecheck`/`build`, `ruff check apps/api`,
`black --check apps/api`, `mypy --strict apps/api/app`, the pytest unit suite
(10 passed, 2 integration tests skipped locally), `bandit` (0 issues), and
`scripts/check_no_egress.sh` (49 files scanned clean; a planted external URL was
verified to fail the check, then removed). The full `docker compose` stack
startup is verified via `scripts/wait_ready.sh` in the CI integration job.

Explicitly deferred out of this milestone: authentication/RBAC, any database
entities beyond the empty Alembic baseline, design tokens and visual/UI work, AI
models and the AI gateway, real-time video/audio infrastructure (LiveKit),
sandbox-runner internals, test coverage thresholds, and golden-set evaluation
content.

## Current status

Full local + containerized loop works for the API: `docker compose up -d` plus
`scripts/wait_ready.sh` builds `apps/api` via its Dockerfile and starts Postgres,
Redis, MinIO, and the API together; `/healthz` and `/readyz` are live and tested.
`services/` and `packages/ui|contracts|eval` are still stubs, and there is no data
model yet (Alembic baseline is a no-op). This README is kept in sync as each
milestone lands.

## Frontend

Both frontend apps use React 18 + TypeScript (strict) + Vite, each on its own dev
port so they can run side by side. ESLint uses `typescript-eslint`'s type-checked
recommended config plus custom rules that ban `any` and non-null assertions.

- `apps/web-recruiter` (port 15173): recruiter console. `App.tsx` is currently
  a deliberate "design system preview" screen exercising every `@aiva/ui`
  component together (score rings, badges, buttons, form fields, loading
  skeletons, empty state) with sample data — explicitly not real candidate
  data, and not a real application page yet. It also references two more
  upcoming milestones: a command palette (arrives with the pipeline, M5) and
  evidence-linked recruiter notes (M11).
- `apps/web-candidate` (port 15174): candidate-facing app, now also built with
  `@aiva/ui` components. Shows an "invitation required" notice (nothing is
  stored before an invite is sent) and an empty state noting that equipment
  checks, a practice room, and the interview runner arrive in later
  milestones — no real pages yet.

## Air-gap policy

No source file may contain a literal external URL. Enforced three ways:

- **ESLint** (implemented in `apps/web-recruiter/eslint.config.js` and
  `apps/web-candidate/eslint.config.js`) bans any string literal or
  template-literal segment starting with `http://` or `https://` in frontend
  source, with a custom error message pointing at the policy.
- **`scripts/check_no_egress.sh`** scans every tracked/untracked-but-not-ignored
  text file (excluding lockfiles and markdown) for `http(s)://` occurrences and
  fails if any line isn't explicitly permitted by `infra/egress_allowlist.txt`
  (a deny-by-default, path + regex allowlist). Current exceptions: the SVG
  `xmlns` attributes in both apps' `index.html`, loopback/internal references in
  `compose.yaml`, the test client's `http://testserver`, and the
  `http://localhost` target polled by `scripts/wait_ready.sh`.
- Production pods run under a default-deny NetworkPolicy (not yet added).

Credentials never live in the repo; all runtime config arrives via validated
environment variables (see `apps/api/app/settings.py`, `.env.example`).
