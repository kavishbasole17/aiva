# AIVA

AI candidate evaluation and interview automation, built on FastAPI + React. AI
judgement (resume scoring, questionnaire evaluation, interview question
generation, evaluation reports) runs on the real Anthropic Claude API via a
single internal gateway (`services/ai-gateway`) — no self-hosted model, no GPU
to operate. See ADR-024 for why the earlier plan (a hand-rolled local/self-hosted
LLM serving layer) was dropped in favor of this.

## Status

Milestones 0 through 11 (core) are delivered and, as of this update, genuinely
CI-verified — see the "Full roadmap" section below for exactly what that
means and the two narrower gaps (Milestone 5's candidates endpoint,
Milestone 7's scheduling integration test) that remain open. In practical
terms: authentication/RBAC/audit, the AI gateway contract, resume ingestion
and scoring, the recruiter console shell, questionnaires, scheduling, the
full consent-precheck-live-interview candidate experience (including a
working `apps/web-candidate` frontend), the M9 live-coding workspace
(sandboxed code execution, autosaved editor, whiteboard, task discussion),
the M10 RAG FAQ + cross-signal evaluation engine with PDF/Excel export, and
the M11 dashboard/blind-screening/scoring-audit/integrity-signals/kits/DSAR
set (see `docs/PLAN.md`'s Milestone 11 section for exactly what each was
scoped to, and why two of those names were deliberately narrowed — ADR-023)
are all built and working end to end against a live stack. Only Milestone
12 (load test, pen-test pass, retention jobs, Helm chart — production
hardening) has not started. Governance docs:
`docs/PLAN.md` (build order and verification evidence), `docs/DECISIONS.md`
(architecture decision records, including ADR-024 — the switch to the
Anthropic API and the branding rebrand away from an earlier reference site),
`docs/RUNBOOK.md` (day-2 operations), and `docs/MODEL_CARD.md` (AI model
inventory — LLM reasoning now runs on the real Anthropic API when configured;
embeddings/STT/TTS remain deterministic mocks pending a local-model
deployment, since Anthropic has no embedding or speech API).

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
  pyjwt (JWT tokens), pyotp (TOTP two-factor authentication), `pymupdf` (PDF
  text extraction), `python-docx` (Word document parsing), `python-multipart`
  (required by FastAPI for file-upload form handling — added after being
  missing initially, which would have broken every resume upload). `httpx`
  was also moved from dev-only to a runtime dependency: `routers_resume.py`
  calls the AI gateway with it directly, and the production Docker image
  only installs runtime dependencies, not the `dev` extras — so this was
  briefly a second instance of the same "works locally/in dev, breaks in the
  real container" class of gap already caught once with the AI gateway's
  prompt path. See the Authentication service and Resume ingest sections
  below for the code built
  on these dependencies.
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
(including that password-only login is rejected once MFA is active).

`test_integration_resume.py` similarly proves the full resume pipeline
end-to-end against a live stack: register → login → create department →
requisition → job description → upload a real generated PDF resume → verify
extracted fields (including that a duplicate upload is rejected with 409) →
create a weight profile → run scoring three times and assert the
`run_fingerprint` and `total_score` are byte-identical every time → verify
the `technical` dimension's evidence is `match_checks` (deterministic) while
every other dimension has gateway-sourced evidence.

**Neither of the above two integration tests is wired into CI yet**:
`.github/workflows/ci.yml`'s `integration` job runs `alembic upgrade head`
against the live stack and executes `test_integration_readiness.py`, but
still not `test_integration_auth.py` or `test_integration_resume.py` — this
thorough coverage exists and passes when run manually/`AIVA_INTEGRATION=1`,
but is not yet part of the automated gate that blocks a bad change.

## Scheduling (`apps/api`) — Milestone 7 (core wired up; email delivery pending)

`app/scheduling.py` — pure slot-generation logic, no I/O yet, notable mainly
for getting timezone arithmetic right from the start rather than as a later
bug fix: an `AvailabilityRule` (local start/end time, slot duration, buffer
between slots, which weekdays count as weekend, excluded dates) plus a date
range and IANA timezone name generates a sorted list of interview `Slot`s
(stored internally as UTC). `_is_real_wall_time()` filters out any local
wall-clock time that doesn't actually exist because of a spring-forward DST
transition, and converting through `zoneinfo` rather than fixed offsets
means fall-back overlaps and DST-boundary duplicate slots are avoided by
construction rather than needing special-cased handling.

`apps/api/tests/test_scheduling.py` proves the hard cases directly rather
than just the happy path: a plain week's worth of slots; the March 2026 US
spring-forward transition correctly produces no slot for the wall-clock time
that doesn't exist (jumping straight from 1:30 to 3:00); the November 2026
US fall-back transition does **not** produce duplicate slots despite the
repeated wall-clock hour; weekends and explicit blackout dates are excluded;
buffer time between slots shifts subsequent start times correctly; an
inverted date range is rejected; and slots generated in a different
timezone entirely (`Asia/Kolkata`) remain correctly UTC-anchored and
chronological.

`app/ics.py` — generates standards-compliant `.ics` calendar invite files
locally, with no external calendar API involved (its own docstring cites
this directly as satisfying an air-gap constraint): proper iCalendar field
escaping (backslashes, semicolons, commas, newlines), UTC timestamp
formatting (treating naive datetimes as UTC rather than raising), and
organizer/attendee fields with an RSVP request. `test_ics.py` covers the
overall structure, the escaping, and the naive-datetime handling.

Within the same update, this went from logic-only to fully wired up:
migration `0005_interview_slots` creates the `InterviewSlot` table with the
same RLS-enforced pattern as every other table, and `app/routers_scheduling.py`
(registered in `main.py`) exposes it as a real API:

- `POST /requisitions/{id}/slots/generate` — runs `generate_slots()` against
  a submitted availability rule and persists the results, skipping any slot
  that already exists as `open` (so calling it again is safe, not
  duplicating), audit-logged
- `GET /requisitions/{id}/slots` — lists all slots and their status
- `POST /slots/{id}/book` — books an open slot for a candidate email
  (rejecting with 409 if it's no longer open) and returns a ready-to-use
  `.ics` invite generated inline via `build_ics()`

**Update (ADR-031)**: `POST /slots/{id}/book` now also emails the `.ics`
invite to the candidate via `app/email.py`'s pluggable provider (log-only by
default — see the Email delivery section below), not just returning it in
the API response. Still not built: T-24h/T-1h reminder emails (a scheduled
job that doesn't exist yet, same "needs a scheduler" gap ADR-029's
retention job has).

## Email delivery (`apps/api`) — ADR-031

`app/email.py` — pluggable outbound email, same mock-now/real-later precedent
as every other external capability here (STT/TTS/LLM backends, ADR-017):
`LogEmailProvider` (default) writes a structured log line for every email
that *would* be sent instead of sending it — exactly the "log-based stub,
swappable for a real provider later" the product spec called for, not a
silent no-op. `SmtpEmailProvider` is a real implementation (stdlib
`smtplib`, run in a thread so it never blocks the event loop) — genuinely
sends mail given real SMTP credentials (`AIVA_EMAIL_BACKEND=smtp` plus the
`AIVA_EMAIL_SMTP_*` settings), not another mock.

Wired into the two places the product spec named: `POST /slots/{id}/book`
now emails the `.ics` confirmation to the candidate (previously only
returned in the API response), and `POST /questionnaires/{id}/invites`
emails the candidate's one-time portal link (`AIVA_CANDIDATE_PORTAL_URL` +
`/questionnaire/{token}`) instead of the recruiter having to copy it out of
the API response and send it manually.

Not built: T-24h/T-1h interview reminder emails (would need a scheduler —
the same gap the retention job's automation, ADR-029, already has) and a
real transactional-email provider integration (SES/SendGrid/etc. — SMTP
covers self-hosted or provider-SMTP-relay delivery, which is most of them,
but not a dedicated API-based integration).

`tests/test_email.py` covers both providers directly: `LogEmailProvider` via
structlog's capture fixture, `SmtpEmailProvider` by mocking `smtplib.SMTP`
(asserting the real `starttls`/`login`/`send_message` call sequence and
message content, including the `.ics` attachment — no real network
connection or SMTP server needed to prove the code is correct).

## Interview sessions (`apps/api`, `services/ai-gateway`, `apps/web-candidate`) — Milestone 8 (core, mock-verified)

The candidate-facing interview loop is now real end to end, following the same
"mock-verified; real models deferred to deployment" precedent as Milestone 3.

**Gateway speech layer** (`services/ai-gateway/app/media.py`): `/v1/stt` and
`/v1/tts` behind typed contracts (`Transcription`, `Synthesis`, both carrying
provider/model ids). Deterministic mock providers are the CI default: mock TTS
synthesizes genuine PCM16 WAV bytes (duration tracks text length at ~150 wpm,
hash-seeded quiet tone); mock STT returns hash-seeded synthetic transcripts with
WAV-header duration parsing. Real backends (`faster-whisper`, `piper`) raise clear
not-deployed errors until weights land; `AIVA_GATEWAY_STT_BACKEND`/`TTS_BACKEND`
flip them at deployment with no call-site changes (ADR-017).

**Interview domain** (`apps/api`):

- `app/precheck.py` — fail-closed validation of device reports: stale suite
  versions rejected outright, every required device (camera/microphone/speaker)
  must be exactly `ok`, connection must be verified (`poor`/`unknown` or a
  sub-minimum bandwidth sample fails).
- `app/interview_engine.py` — pure adaptive loop: fingerprinted question plans
  derived from objective JD-vs-resume gaps (missing skills, verified skills,
  stated-vs-required years); answers covering enough of a topic's expected
  points advance, thin answers spend that topic's single scripted probe first;
  transcripts replay deterministically. The LLM stays out of interview control
  flow by design (ADR-018).
- `app/routers_interview.py` — staff endpoints create sessions against booked
  slots (raw join token shown once, only its SHA-256 stored), list session
  summaries per requisition, and fetch full attributed transcripts. Public
  token-gated endpoints drive the lifecycle:
  `pending_consent → consent_granted → precheck_passed → active → completed`
  (with terminal `declined`/`aborted`). Every gate fails closed — no question
  is served before version-matched granted consent plus a passed pre-check;
  expired links answer 410, wrong-state mutations answer 409. Turns accept
  typed text or base64 audio (routed through gateway STT) and persist STT
  confidence/model/audio-hash per turn; TTS read-aloud is proxied same-origin.
- Migration `0006_interview_sessions` adds RLS-forced tables (bootstrap-safe
  policies for the public token flow); migration `0007_app_role_grants_backfill`
  fixes a latent privilege gap: migrations 0004/0005 never granted their tables
  to the runtime `aiva_app` role, which would have failed those features on any
  fresh deployment — caught by this milestone's integration test, fixed forward
  rather than editing applied history.
- New settings: `AIVA_INTERVIEW_TOKEN_HOURS` (default 48).

**Candidate portal** (`apps/web-candidate`) — no longer a placeholder:

- Join page (token entry, pre-filled from invite link query param).
- Consent screen rendering the exact statement text and version; decline is
  one click and terminal.
- Device pre-check gate: live camera preview, microphone level detection via
  WebAudio (silence counts as degraded, not ok), speaker tone confirmation,
  and a real connection sample (health round-trip latency + openapi.json
  throughput in kbps).
- Live HUD: status chips, elapsed timer, topic progress spine, current question
  card with gateway-backed "Read aloud", answering by typed text or recorded
  audio (MediaRecorder → base64 → gateway STT), transcript drawer, and an
  explicit end-session control. React Router replaces the static screen; the
  Vite dev proxy keeps all traffic same-origin.

**Verification**: `test_integration_interview.py` drives the full lifecycle
against the live stack including the containerized gateway — gates reject early
start/failing pre-check/stale consent versions, consent denial is terminal, the
first answer round-trips audio→STT→transcript with model attribution, the engine
closes within budget, terminal state rejects further turns, and staff detail
shows the consent record and attributed transcript. The CI integration job now
runs this plus the previously-unwired auth/resume/questionnaire lifecycle tests.

Deferred within M8 (tracked): LiveKit room infrastructure and client SDK tokens
(needs media infra in compose; contracts unchanged when it lands),
faster-whisper/Piper weights (GPU deployment), InsightFace identity verification
and MediaPipe proctoring signals (M11 integrity work), the §13 `--network none`
end-to-end proof.

## Live-coding workspace (`services/sandbox-runner`, `apps/api`, both web apps) — Milestone 9 (delivered)

A new microservice, `services/sandbox-runner`, executes candidate-submitted
Python/JavaScript under process-level isolation: a dedicated unprivileged
`sandbox` account (setuid-dropped into per execution — the server itself
stays root specifically to enable that drop, see ADR-019), POSIX rlimits
(CPU seconds, address space, process count, open files, output size), a
routeless network namespace via `unshare --net`, an ephemeral per-run temp
directory, and a hard wall-clock timeout that kills the whole process
group. It fails closed (503) if `unshare` isn't available rather than
running code unisolated. This is process-level isolation on a shared
kernel, not a container/VM boundary — ADR-019 states that limit plainly; a
hardened runtime (gVisor/Firecracker/nsjail) is deferred to M12.

`apps/api` migration `0009_workspace` adds five session-scoped, RLS-forced
tables (coding tasks, autosaved code snapshots, code executions, whiteboard
strokes, discussion messages) and `routers_workspace.py` gives staff
(JWT) task creation and full read/annotate access, and the candidate (raw
token, same single-use discipline as the interview/questionnaire flows)
autosaved editing, sandboxed run requests proxied to sandbox-runner,
whiteboard strokes, and discussion — candidate writes gated to an ACTIVE
session. Screen share is a stable public endpoint returning 501 rather than
a fake success: it needs WebRTC/LiveKit infrastructure this compose stack
doesn't run, same mock-now/hardened-at-deployment precedent as the STT/TTS
backends (ADR-017), not a new deferral pattern.

`apps/web-candidate` gained a Workspace tab in the interview HUD (code
editor with autosave + run + output, a canvas whiteboard, a discussion
thread) and `apps/web-recruiter` gained a Sessions list and an Interview
Session detail page (transcript, task creation, a live polled read-only
view of the candidate's code and run history, a bidirectional whiteboard,
discussion).

**Verification**: `test_integration_workspace.py` drives task creation →
candidate autosave → sandboxed run → staff sees the result, whiteboard
strokes from both sides render together, discussion round-trips both ways,
cross-org staff access 404s, and candidate writes reject with 409 once the
session is terminal — against the live stack including a real
sandbox-runner container. `services/sandbox-runner`'s own unit tests prove
the isolation directly rather than assuming it: a timeout kills an infinite
loop, RLIMIT_AS stops an unbounded allocation, and a real socket connect
attempt from inside the sandbox is confirmed blocked by the network
namespace (`test_network_is_isolated`). All quality gates green
(ruff/black/mypy --strict/bandit/pytest) on both `apps/api` and the new
`services/sandbox-runner`; a `sandbox-quality` CI job mirrors
`gateway-quality`.

**A security review run against this diff before M9 was called done found a real
isolation gap**: the first cut setuid-dropped every execution into the *same* fixed
sandbox account, so the "ephemeral per-run temp directory" claim didn't actually hold
under concurrency — any run's code could list the world-listable base-image `/tmp`, find
another live run's directory (owned by the identical shared uid), and read or overwrite
it; the shared uid also let concurrent runs see and signal each other via `/proc`. Fixed
via a per-run `UidPool` (never shared, acquired/released around each execution, blocking
rather than reusing a uid if the pool is briefly exhausted) plus PID-namespace isolation
(`unshare --pid --fork`) — see ADR-020, and
`test_pid_namespace_hides_other_processes`/`test_uid_pool_never_hands_out_the_same_uid_twice_concurrently`
for the tests that prove it rather than assume it.

Deferred within M9 (tracked): a real-time collaborative editor — autosave +
poll (same shape as M6's questionnaire autosave), not live keystroke
sync via CRDT/OT; the screen share backend itself (ADR-019); a hardened
sandbox runtime (M12).

## RAG FAQ and evaluation engine (`services/ai-gateway`, `apps/api`, both web apps) — Milestone 10 (delivered)

`services/ai-gateway` gained a `/v1/embed` endpoint behind an `EmbeddingProvider`
interface — `MockEmbedder` (deterministic, hash-seeded, L2-normalized 384-dim
vectors) now, a real sentence-transformer deferred to GPU deployment, same
mock-now/hardened-later split as the STT/TTS backends (ADR-017). Only the
embedding *model* is mocked — retrieval is real: `apps/api` migration
`0010_faq_and_evaluation` adds `faq_documents` with a genuine pgvector
column and an ivfflat cosine-similarity index, and `routers_faq.py`'s
candidate-facing `ask_faq` runs an actual `ORDER BY embedding <=> :query`
search, then feeds only what retrieval found into a new `faq_answer`
gateway prompt — the LLM can't invent the retrieval step. Staff write FAQ
documents per requisition; the candidate asks questions from a new FAQ tab
in the interview Workspace (raw-token discipline, same as every other
public endpoint).

`evaluation_engine.py` deterministically aggregates resume score,
questionnaire completion, interview completeness, and coding-task pass
rate into one weighted verdict — same "arithmetic and thresholds live only
in application code, never in a prompt" rule `scoring.py` established. The
gateway-backed `evaluation_summary` narrative is additive-only: if the
gateway is unreachable when a report is generated, the persisted
`EvaluationReport` still has its full deterministic verdict and component
breakdown, just no narrative. `report_export.py` renders PDF (reportlab)
and Excel (openpyxl) straight from that persisted payload, streamed on
demand from new staff-only export endpoints — see ADR-021. `apps/web-recruiter`
gained an Evaluation section on the resume detail page (generate, view,
download).

**Verification surfaced a real pre-existing bug, fixed forward**:
screenshot-testing the new Evaluation panel crashed `ResumeDetail.tsx` on
any resume with a scoring run — `GET .../scoring-runs` never returned
`checks`/`dimensions`, but the page's "latest run" selector assumed it
did. Fixed by taking the list's already-newest-first first entry directly.
Unrelated to M10's own code but blocking its verification, so fixed here
rather than left for a future milestone to rediscover — same precedent as
the M8/M9 grants-backfill and sandbox-isolation findings.

`test_integration_faq.py` proves retrieval returns genuinely relevant
documents and degrades gracefully with zero FAQ documents present;
`test_integration_evaluation.py` proves every component populates from
real data, PDF/Excel exports have valid file signatures, and cross-org
access to a report 404s. `evaluation_engine.py`'s weighting/verdict-banding
is unit-tested directly. All quality gates green
(ruff/black/mypy --strict/bandit/pytest) on `apps/api` and
`services/ai-gateway`.

Deferred within M10: archiving generated reports to MinIO/retention
(left to M12, as originally scoped — exports are generated on demand and
streamed, not persisted as artifacts); a real sentence-transformer
embedding backend (GPU deployment).

## Questionnaires and candidate invites (`apps/api`) — Milestone 6 (core, delivered)

`app/questionnaire_service.py` — pure logic, no I/O: six question types
(`multiple_choice`, `yes_no`, `rating`, `long_text`, `short_text`,
`file_upload`); `validate_questions()` enforces safe IDs (no duplicates, a
restricted character set), a required prompt, a known type, and at least two
options for multiple-choice; `missing_required_answers()` checks which
required questions remain unanswered. `generate_invite_token()` produces a
secure random token and returns both the raw value (given to the candidate)
and its SHA-256 hash (the only thing ever stored) — the same
never-store-the-raw-secret pattern used for refresh tokens in Milestone 2.

`app/routers_questionnaire.py` exposes this as a real API, split into staff
endpoints and public (unauthenticated, token-gated) ones:

- `POST /requisitions/{id}/questionnaires` — create a questionnaire (staff)
- `POST /questionnaires/{id}/invites` — generate a candidate invite; returns
  the raw token once (staff; new setting `invite_token_days`, default 14)
- `GET /public/questionnaires/{raw_token}` — fetch the questionnaire and any
  saved answers, no login required — just possession of the token
- `PUT /public/questionnaires/{raw_token}/responses` — save a draft or submit
  (submission is rejected with the list of missing questions if any required
  question is unanswered); every save appends to an `history` array on the
  response row, so edits are traceable, not just the final state
- `GET /requisitions/{id}/questionnaire-responses` — list responses (staff)

New data model (migration `0004_questionnaires`, same RLS-enforced pattern
as before): `questionnaires`, `questionnaire_invites` (stores only the token
hash, an expiry, and a completion timestamp), `questionnaire_responses`
(answers, edit history, missing-required list, submission state).

**Code-quality note**: `create_invite`'s handling of the settings-derived
invite expiry window looks like leftover/unfinished code — it constructs an
always-`None` value via an `if False` conditional, imports `get_settings` a
second time under an alias that's never used, and reads the expiry from the
module-level cached settings rather than the request-injected settings used
everywhere else in the codebase. It still works (the cached settings are
equivalent in practice), but it doesn't match the codebase's own established
pattern and looks unfinished.

`main.py` now registers `questionnaire_router`, so this is reachable through
the running API. `apps/api/tests/test_questionnaire_unit.py` covers the pure
logic (token round-trip/uniqueness, question validation, missing-required
detection), and `apps/api/tests/test_integration_questionnaire.py` proves
the full lifecycle against a live stack: create a questionnaire, invite a
candidate, autosave a partial answer (public endpoint, no auth), verify
submission is rejected while a required question is missing, submit
successfully once complete, and confirm the invite is genuinely single-use —
both re-fetching and re-submitting after completion correctly return 409.
Like the two integration tests before it, this one is not yet wired into
`.github/workflows/ci.yml`'s `integration` job (still only
`test_integration_readiness.py`) — it exists and passes when run manually.

No frontend consumed any of this at the time this section was written; a
recruiter-facing questionnaire builder, invite flow, and response viewer, plus
a candidate-facing fill-out page, now do — see "Recruiter console: requisitions,
job descriptions, resume upload, questionnaires, scheduling" below.

## Recruiter console — Milestone 5

`apps/web-recruiter` gained its first real, working screens, replacing the
Milestone 1 design-system demo:

- `src/api/client.ts` — a typed API client (`API_BASE = "/api"`, proxied by
  Vite's dev server to `http://localhost:18000`, stripping the `/api` prefix)
  covering login, listing candidates for a requisition, fetching a resume's
  full detail, and listing scoring runs.
- `src/auth.ts` — a minimal client-side auth store (`useSyncExternalStore`,
  no state library) persisting the access token to `localStorage` and
  pushing it into the API client.
- `src/pages/Login.tsx` — a real login screen calling `POST /auth/login`.
- `src/pages/Candidates.tsx` (route `/pipeline?req=<requisition-id>`) — the
  pipeline view: lists every resume uploaded against a requisition with its
  latest score and verdict (color-coded badge), sortable by score or name,
  filterable by name/email, with loading skeletons and an empty state.
- `src/pages/ResumeDetail.tsx` (route `/resumes/:id?req=<requisition-id>`) —
  a candidate detail page built on a new shared component, `EvidenceSpine`
  (see below): renders every extracted field and every scored dimension as
  one continuous, scroll-linked timeline, each entry expandable to show its
  exact source quote and metadata (page, character offsets, confidence,
  extractor, or gateway evidence references). This is the "Evidence Spine
  v1" referenced in the roadmap, now a real, working UI, not just a backend
  concept.
- `App.tsx` now does real client-side routing (`react-router-dom`): a
  protected-route wrapper redirects to `/login` when signed out, plus a
  persistent header with sign-out.
- `GET /requisitions/{id}/candidates` was added to `apps/api/app/routers_resume.py`
  to serve the pipeline view — its response shape (resume id, filename,
  candidate email, latest run's score/verdict/fingerprint) matches exactly
  what the frontend expects; this endpoint did not exist when the Milestone
  4 API was first documented above.

Requisition browsing, job-description, resume-upload, questionnaire, and
scheduling UI were all built later (ADR-026, see the section below) — the gap
noted at the time this milestone was first written no longer applies. The MFA
login gap noted here too has since been closed (ADR-032): the login screen
now prompts for a 6-digit code when the backend's `/auth/login` response
indicates one is required, and a new `/security` page drives the
enroll-then-activate flow, both consuming MFA endpoints that had existed on
the backend since Milestone 2 with no frontend ever built for them. Per
`docs/PLAN.md`, still deliberately deferred within this milestone: Playwright
end-to-end and accessibility (axe) test wiring, 60fps performance trace
capture, Lighthouse audits, a command palette, and saved pipeline views — the
latter two are treated as hardening-stage work for Milestones 11/12, not gaps
in the current milestone.

## Recruiter console: requisitions, job descriptions, resume upload, questionnaires, scheduling (ADR-026)

Closes the biggest remaining gap in the recruiter console: every domain
capability below had working, tested backend logic with zero UI to reach it
— a recruiter could not create a job description, upload a resume, build a
questionnaire, or generate interview slots without calling the API directly.

Two backend endpoints were added because no way existed to list existing
records at all (only get-by-id): `GET /orgs/{id}/departments` and
`GET /orgs/{id}/requisitions` (`app/routers_org.py`), plus
`GET /requisitions/{id}/job-description` (latest version, `app/routers_resume.py`)
and `GET /requisitions/{id}/questionnaires` (`app/routers_questionnaire.py`).
`GET /requisitions/{id}/questionnaire-responses` was also extended to include
`candidate_email` and `answers`, both previously omitted from the list
response with no way to see who a response belonged to without a raw DB
query.

`apps/web-recruiter` gained five new pages: `Requisitions.tsx` (the new
default landing route — lists departments/requisitions, creates both),
`RequisitionDetail.tsx` (a requisition's hub: view/create the job
description, navigate to every other page for that requisition),
`ResumeUpload.tsx` (drag-and-drop multi-file upload against a requisition,
then a "Score uploaded resumes" action that creates a default weight profile
— technical 30 / experience 20 / domain 15 / education 10 / certifications 10
/ soft_skills 10 / stability 5, matching `scoring.py`'s `DEFAULT_WEIGHTS` —
and runs a scoring pass per resume), `Questionnaire.tsx` (a quick-start
template covering notice period, salary expectations, work authorization,
relocation, remote preference, a self-assessment rating, certifications,
portfolio links, availability, and interview-time preference — matching the
product spec's quick-start list — plus invite generation and a response
list), and `Scheduling.tsx` (generate availability slots, list them, book one
for a candidate, view the resulting `.ics` invite inline). `packages/ui`
gained a `Select` component (native select, styled to match `Input`/`Textarea`)
since none of the existing primitives covered a dropdown.

`apps/web-candidate` gained a public, token-gated questionnaire page
(`/questionnaire/:token`) — the only candidate-facing surface for
questionnaires ADR yet had zero UI for. Renders each of the six question
types (button groups for `yes_no`/`rating`/`multiple_choice`, text inputs for
`short_text`/`long_text`), autosaves on a debounce, and surfaces the exact
missing-required-question list the API returns on a rejected submit.

Verified against a live stack, not just read: brought up the full compose
stack fresh (`docker compose up --build`, migrations 0001→0013 applied),
then exercised the entire new surface directly over HTTP with `curl` —
register → login → create department → create requisition → list both →
create job description → fetch it back → create questionnaire → invite →
public fetch → public submit → staff response list (with the new
`candidate_email` field populated correctly) → generate scheduling slots →
list them → upload a resume → create a weight profile → run a scoring pass
(round-tripping through the AES-256-GCM-encrypted `full_text`/extracted-field
columns from ADR-025 transparently) → pipeline view showing the score. Every
step returned the expected shape. The existing domain-lifecycle integration
test suite was also re-run against the same live stack after these changes:
24/26 pass (the 2 failures are the pre-existing sandbox-runner/Docker
Desktop anomaly noted elsewhere in this document, unrelated to this work).

**Update — now verified**: the live TypeScript compile/build this section
originally flagged as unverified (blocked by Windows-host/WSL2-filesystem
tooling friction: UNC-path-unaware `cmd.exe` subprocesses, a drive-letter
workaround that hit a stale pnpm store signature, a resolved `vite` binary
Windows refused to execute) was unblocked by installing a user-local Node.js
binary directly inside the WSL2 distro (no `sudo`, no system package
manager — a tarball extracted to `~/.local/node`) and running `pnpm` fully
natively there instead of bridging Windows and WSL2 filesystems. That single
change — do the whole toolchain on one side of the filesystem boundary —
is what the earlier attempts were missing.

With a real compiler available, `tsc --noEmit` on `apps/web-recruiter`
surfaced 8 genuine type errors from this repo's `noUncheckedIndexedAccess`
strict-mode flag (`packages/ui`'s `tsconfig.json`, predating this session):
array-index access like `rows[index]` types as possibly-`undefined`, not the
element type. All were in `ResumeUpload.tsx`'s upload/scoring loops — fixed
by iterating `rows.entries()` instead of indexing, which gives a properly
narrowed element with no assertion needed. `eslint` then caught a second,
independent issue: six uses of `requisitionId!` (in `Questionnaire.tsx` and
`Scheduling.tsx`) violated this repo's `@typescript-eslint/no-non-null-assertion`
rule — non-null assertions compile fine but are banned here since they can
silently hide a real `undefined` at runtime. Fixed by rebinding the
`useParams()` value to a fresh `const` after the component's own
`if (!id) return null` guard, which both the compiler and linter accept
as genuinely narrowed (the hand-reviewed original code had relied on
narrowing propagating into nested closures, which — confirmed here against a
real compiler, not assumed — it does not for this pattern). Every one of
these was a real bug, not a style nit: an unguarded `undefined` reaching
`fetch()` would throw at runtime exactly when a recruiter clicked the
affected button.

`apps/web-recruiter` and `apps/web-candidate` both now pass `tsc --noEmit`,
`vite build` (production bundle, fonts and all), and `eslint` with zero
errors. Both production builds were also served locally (`vite preview`)
and confirmed to return real HTML with the correct page titles — not just
"the bundler didn't crash." The two bugs caught by hand-review before any of
this (the candidate-questionnaire response-parsing bug and the unnecessary
`eslint-disable`) were real too — compiler + linter verification and careful
hand-review caught different, non-overlapping classes of bug here, which is
itself worth noting rather than assuming either alone would have been enough.

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
- `EvidenceSpine.tsx` — added for Milestone 5: renders a list of evidence
  nodes (each either a scored dimension or an extracted field) as a single
  vertical timeline with a scroll-linked progress line (skipped under
  reduced motion), where every node expands on click to reveal its exact
  source quote and metadata. This turns the backend's evidence-citation
  discipline (Milestones 3–4) into a concrete, reusable UI pattern.

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

- `packages/eval` — real golden-set harness (see its section below);
  `packages/contracts` still holds only a placeholder export.
- `services/ai-gateway` — fully built (Milestone 3 + M8 speech layer);
  `services/worker`, `services/sandbox-runner` — empty directories
  (`.gitkeep` only), reserved but not started (Milestones 9+).

## Resume ingest and matching (`apps/api`) — Milestone 4

`app/text_extract.py` — span-preserving text extraction. `load_document_text()`
handles PDF (`pymupdf`, page-by-page), DOCX (`python-docx`), and plain text,
producing a `DocumentText` with the full text, per-page character-offset
spans, and a SHA-256 content hash. `extract_fields()` deterministically pulls
out: email, phone, and LinkedIn URL (regex), technical skills (a fixed ~50-term
lexicon), years-of-experience claims (regex), and a candidate name (a naive
heuristic: the first short, all-alphabetic line). Every single
`ExtractedField` carries its page number, start/end character offsets, the
literal source quote, a confidence score, and which extractor produced it
(`regex`/`lexicon`/`heuristic`) — the same evidence-citation discipline
established for the AI gateway, applied to deterministic parsing too.

`app/matching.py` — explicitly documented in its own module docstring as
"Deterministic matching checks — computed in code, never by the LLM." Given
a `JobRequirements` (required skills, preferred skills, minimum years),
`run_match_checks()` produces one `MatchCheck` per objective fact (each
required skill present or not, preferred-skill coverage, stated years vs.
requirement), each with a pass/fail, a human-readable detail string, and
which extracted fields it's based on. `match_ratio()` gives an overall
fraction; `to_payload()` serializes for API responses. This is a deliberate
architecture decision: objective, checkable facts are computed by plain code
and never left to the AI model's judgment — the AI (see Milestone 3 above)
is reserved for genuinely subjective evaluation, and even then must always
cite its evidence.

`app/scoring.py` — versioned, weighted scoring that closes the loop between
the AI gateway and the deterministic matching layer. Its module docstring
states the principle directly: **"The LLM never performs arithmetic or
threshold comparisons; it only produces qualitative dimension judgements,
each of which must cite evidence."** Seven scoring dimensions (technical,
experience, domain, education, certifications, soft_skills, stability) are
combined via a versioned, fingerprinted `WeightProfile` (default weights
30/20/15/10/10/10/5) into a single 0–100 score and one of four verdicts
(`auto_reject`, `hold`, `shortlist`, `highly_recommended`) via configurable
thresholds. `technical_dimension_from_checks()` derives the technical
dimension directly from `matching.py`'s deterministic match ratio — no AI
involved for that dimension at all. Every scoring run gets a
`run_fingerprint` (a hash of the resume, checks, dimension scores, and
profile version) so any specific score can be exactly reproduced and
verified later — directly relevant to defensibility of a hiring decision.

The data model gained five new tables in migration `0003_resume_scoring`
(same RLS-enforced, organization-scoped pattern as Milestone 2):
`job_descriptions`, `resume_documents`, `extracted_fields` (persists every
`ExtractedField` from `text_extract.py`), `weight_profiles`, and
`scoring_runs`. This migration and the underlying models are complete and
already in the database schema.

`app/routers_resume.py` now exposes the full pipeline as a real HTTP API,
registered in `main.py`:

- `POST /requisitions/{id}/job-description` — create a job description with
  required/preferred skills and minimum years
- `POST /requisitions/{id}/resumes` — upload a resume (PDF/DOCX/text, 10MB
  limit); sniffs the real MIME type from file bytes rather than trusting the
  filename, rejects an empty file, and rejects an exact duplicate (by content
  hash) already uploaded to the same requisition; extracts and persists every
  field immediately
- `GET /resumes/{id}` — the resume plus every extracted field with its full
  evidence (page, offsets, source quote)
- `POST /requisitions/{id}/weight-profiles` — create an organization-scoped,
  versioned scoring profile (auto-increments version per name)
- `POST /requisitions/{id}/scoring-runs` — the core endpoint: loads the
  resume, the requisition's latest job description, and the chosen weight
  profile; runs the deterministic match checks for the `technical` dimension;
  calls the **live AI gateway over HTTP** (`AIVA_AI_GATEWAY_URL`) once per
  remaining dimension (experience, domain, education, certifications,
  soft_skills, stability), each with a seed key derived from the resume's
  content hash + profile fingerprint + dimension name for reproducibility;
  combines everything into a total score and verdict; persists the full
  result with its fingerprint; and writes an audit event
- `GET /requisitions/{id}/scoring-runs` — list past runs for a requisition

The API and AI gateway are now genuinely connected: `Settings.ai_gateway_url`
(new `AIVA_AI_GATEWAY_URL` env var) points the API at the gateway, and
`compose.yaml` wires `http://ai-gateway:9100` in for the containerized stack.
This closes the "run side by side without talking" gap noted earlier for
Milestone 3.

`apps/api/tests/test_text_extract.py` is a thorough new test suite: it
generates real PDF and DOCX files in-memory (via `pymupdf`/`python-docx`)
and round-trips them through extraction, asserting every field's character
span resolves back to its own value, multi-page PDFs map fields to the
correct page, content hashing is deterministic, and a corrupted PDF raises
rather than silently returning garbage.

**What's still missing**: no frontend calls any of this yet — it's a
complete, working API, testable directly, but not yet reachable through
either web app's UI.

## AI gateway (`services/ai-gateway`) — Milestone 3 (real backend: Anthropic API, ADR-024)

A standalone FastAPI service (own `pyproject.toml`, same quality tooling as
`apps/api`: ruff, black, mypy strict, bandit, pytest), configured via
`AIVA_GATEWAY_*` env vars (`llm_backend`, defaulting to `mock`;
`anthropic_api_key`; `anthropic_model`, defaulting to `claude-sonnet-5`).

- `app/contracts.py` — the gateway's stable response contract. `JudgementBase`
  requires `rationale`, `confidence` (0–1), and `cited_span_ids` (at least
  one) on every judgement; `DimensionScore` and `ResumeFieldExtraction`
  extend it. This is a hard constraint (referenced in-code as "constraint
  8.1"): **no AI output can exist without evidence it can be traced back
  to** — this is the foundation for the "Evidence Spine" referenced in the
  Milestone 5 roadmap entry.
- `app/prompts.py` (`PromptRegistry`) — loads `.txt` prompt templates, does
  simple `{{variable}}` substitution, and computes a content-hash `version`
  for each prompt so every generation can record exactly which prompt version
  produced it. Directory resolution was fixed to try the current working
  directory's `prompts/` first, falling back to a path relative to the
  package — the original module-relative-only resolution would have pointed
  at the wrong location once the package is `pip install`-ed into the Docker
  image (its `__file__` then resolves inside `site-packages`, not `/app`),
  which plausibly explains prompts not being found in a containerized run
  even though local development worked. A new `AIVA_GATEWAY_PROMPTS_DIR`
  setting can override the directory explicitly.
- `prompts/dimension_score.txt` — the first real prompt, for scoring one
  evaluation dimension against a job description. It explicitly instructs the
  model: score only what the candidate's own documents/statements support,
  cite at least one evidence span id, and never infer emotion, personality,
  or confidence — a deliberate anti-hallucination/anti-bias guardrail baked
  into the prompt itself.
- `MockBackend`'s deterministic fill now echoes back a matching input value
  for a field when one exists (e.g. reflecting the requested `dimension` back
  in the output) rather than always synthesizing a placeholder, making mock
  output more realistic for testing.
- `app/backends.py` — a pluggable `Backend` interface with two
  implementations: `MockBackend` (deterministic, hash-seeded fake data that
  still validates against the real response schema — used by CI and by
  `docker compose up` with zero setup) and `AnthropicBackend` (calls the real
  Anthropic API with a **forced tool_use call** whose `input_schema` is the
  exact Pydantic response-model schema, so the model's only possible reply is
  schema-shaped — the same "impossible to return invalid output" property
  `VllmBackend`'s `guided_json` gave the earlier self-hosted-model plan, now
  without operating any GPU inference; see ADR-024 for why that plan was
  dropped. `temperature=0` for closest-to-reproducible output, though unlike
  `MockBackend` this is not a byte-identical guarantee — documented, not
  glossed over. `GenerationResult` records the `prompt_version`, `backend`,
  and `model_id` alongside every generated result, giving full provenance for
  any AI output.

`app/main.py` assembles a real, running FastAPI app (`create_app()`, same
`docs_url=None`/`openapi_url="/openapi.json"` pattern as `apps/api`) exposing:

- `GET /healthz`
- `GET /prompts` — lists every loaded prompt with its content-hash version
- `POST /v1/generate` — the core endpoint: given a `prompt_id`, a
  `response_model` name, template `inputs`, and a `seed_key`, it renders the
  prompt, runs it through the configured backend (mock or anthropic), validates
  the result against the response contract, and returns the data plus its
  `prompt_version`/`backend`/`model_id` provenance. Missing template inputs,
  an unknown prompt, or an unknown response model all return clear 400/404
  errors rather than failing silently.

`apps/api/tests/test_gateway.py`-equivalent tests (in
`services/ai-gateway/tests/`) prove the mock backend is genuinely
deterministic: the same request repeated returns byte-identical output, and
changing an input (e.g. the dimension being scored) changes the output
accordingly.

The gateway now has a `Dockerfile` (same multi-stage, non-root pattern as
`apps/api`) and is wired into `compose.yaml` as the `ai-gateway` service, port
19100 (host) / 9100 (container), running in `mock` backend mode by default
with its own healthcheck; set `ANTHROPIC_API_KEY` and
`AIVA_GATEWAY_LLM_BACKEND=anthropic` in a local `.env` to switch it to real
inference with zero code changes. It is now called by the main API's
scoring-run endpoint (see the Resume ingest and matching section above) — the
two services are genuinely connected, not just running side by side.

Per `docs/PLAN.md`, Milestone 3 is now marked delivered — labeled
"mock-verified for CI/tests; real inference via the Anthropic API when
configured (ADR-024)" — with all 7 CI jobs green (including the previously-
failing golden-set-against-live-container step, after the prompts-directory
fix above; CI itself always runs on `mock`, so it needs no API key or secret).
`services/ai-gateway/tests/test_anthropic_backend.py` proves the real-backend
request/response contract directly (forced tool_choice, schema validation,
schema-invalid-output rejection, missing-tool_use rejection) by mocking the
Anthropic SDK client — no network calls, no key needed to run that suite.
Not part of this milestone: pulling real embedding/STT/TTS model weights
(Anthropic has no API for those — see the Embeddings and Interview sessions
sections below), and evaluation thresholds tuned against real model output
rather than the mock backend's synthetic fill.

## Golden-set evaluation harness (`packages/eval`)

`packages/eval` now has real content: `golden/cases.jsonl` defines three
test cases against the AI gateway (two `DimensionScore` cases — technical and
communication scoring — and one `ResumeFieldExtraction` case), and
`tests/test_golden_set.py` runs each case against a live gateway instance
(skipped unless `AIVA_EVAL_GATEWAY_URL` is set), asserting the response is
schema-valid, that citing evidence/a source quote is present, and critically
that **the exact same request produces byte-identical output on a second
call** — proving the gateway's determinism guarantee holds against real
cases, not just unit tests.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request, as
independent jobs:

- `no-egress` — runs `scripts/check_no_egress.sh` against the full checkout
- `compose-config` — validates `compose.yaml` with `docker compose config -q`
- `web` — pnpm install, lint, typecheck, and build across all frontend workspaces
- `api-quality` — ruff, black `--check`, mypy (strict), and bandit against `apps/api`
- `gateway-quality` — the same checks (ruff, black, mypy strict, bandit, unit
  tests) against `services/ai-gateway`
- `sandbox-quality` — the same checks against `services/sandbox-runner`, plus
  installing `nodejs` so the JavaScript executor's unit tests run too
- `api-tests` — runs the API's offline unit test suite
- `integration` — boots the full `docker compose` stack (now including
  `sandbox-runner`), applies migrations, runs `test_integration_readiness.py`
  against the live services (`AIVA_INTEGRATION=1`), then runs the seven
  domain lifecycle suites (auth/RBAC, resume→scoring roundtrip, questionnaire
  single-use flow, interview consent/pre-check/STT-loop, the M9 workspace,
  the M10 RAG FAQ, and the M10 evaluation engine) against the live stack
  including the containerized gateway and sandbox-runner
  (`AIVA_AI_GATEWAY_URL`/`AIVA_SANDBOX_URL` pointed at their container
  ports), then runs the golden-set evaluation suite against the live AI
  gateway before tearing the stack down

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
- The design system's brand color (`--signal`) is an original palette
  (indigo-violet `#6C5CE7` dark theme / `#4B3ED1` light theme), with a
  separate, higher-contrast derived color (`--signal-text`) so small colored
  text still meets accessibility contrast guidelines — both re-verified
  ≥4:1 (large UI) and ≥9:1 (`--signal-text`, small text) (ADR-014, values
  superseded by ADR-024 when the palette was rebranded away from an earlier
  reference site)
- All AI reasoning (resume scoring, questionnaire evaluation, interview
  question generation, evaluation reports) runs on the real Anthropic API
  through `services/ai-gateway`, replacing an earlier plan to self-host an
  open-weight model; the gateway's deterministic mock backend remains the
  default for CI/local runs with no API key (ADR-024)
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

All model inference routes through the single `ai-gateway` service. `docs/MODEL_CARD.md`
records the candidate model/provider for each capability and its current status:

| Capability | Provider/model | Milestone |
|---|---|---|
| LLM reasoning/scoring | Anthropic API, `claude-sonnet-5` (mock backend for CI/zero-setup) | M3; real backend since ADR-024 |
| Embeddings | all-MiniLM-L6-v2 (384-dim, local) — no embedding API exists to call instead | M3/M10 (mock-verified; weights pending local deployment) |
| Resume parsing (NER) | spaCy pipeline | M4 |
| OCR fallback | PaddleOCR / Tesseract | M4 |
| Speech-to-text | faster-whisper large-v3 / distil-large-v3 — no speech API exists to call instead | M8 interface shipped, mock-verified; weights pending deployment |
| Text-to-speech | Piper (ONNX voices) — no speech API exists to call instead | M8 interface shipped, mock-verified; voices pending deployment |
| Identity verification | InsightFace ArcFace (with consent gate) | deferred to M11 integrity work |
| Proctoring signals | MediaPipe Face Mesh | deferred to M11 integrity work |
| Reranker | bge-reranker-v2-m3 | M10 |

Licensing rule: Apache-2.0/MIT preferred; anything under a bespoke community
license is flagged for human legal review before integration.

## Full roadmap (per docs/PLAN.md)

`docs/PLAN.md` is a running status ledger; Milestones 0-8 (core) are now
listed as "Delivered and CI-verified." **Update on the CI-verification
caveat this document has tracked since Milestone 5**: that gap is now
substantially closed. `.github/workflows/ci.yml`'s `integration` job has
been directly re-checked and now genuinely runs all four integration test
files in sequence — `test_integration_auth.py`, `test_integration_resume.py`,
`test_integration_questionnaire.py`, and `test_integration_interview.py` —
alongside the original `test_integration_readiness.py` in an earlier job.
So Milestones 2, 4, 6, and 8's core claims of being proven against a live
stack in CI are now accurate as written, not just as intended.

Two narrower gaps flagged earlier remain open and PLAN.md does not claim
otherwise: the `GET /requisitions/{id}/candidates` endpoint added for
Milestone 5 still has no automated test coverage at all (not merely
unwired from CI — no test exists for it in the codebase); and Milestone 7
(scheduling) still has no dedicated integration test — only unit tests
(`test_scheduling.py`, `test_ics.py`) plus the generic readiness check,
not an end-to-end proof against a live stack. Neither of these indicates
missing feature work — both areas are built and function correctly when
exercised manually or via unit test — only that their automated safety
net is narrower than the rest of the platform's.

**This tracking was not academic**: while building Milestone 8's
integration flow, the team discovered that migrations `0004` (questionnaires)
and `0005` (interview slots) never granted database privileges to `aiva_app`
— the restricted role the running API actually connects as. Every real
write to a questionnaire or an interview slot would have failed with a
database permission error, despite all the code and unit tests being
correct and passing. This is exactly the class of problem a live-stack
integration test is designed to catch, and it went undetected until
Milestone 8's own manual integration testing surfaced it — before the CI
gap above had been closed. It's now fixed via a backfill migration
(`0007_app_role_grants_backfill`) rather than editing already-applied
migration history. This is a concrete, already-realized example of why the
CI-wiring gap this document tracked was worth closing, not just a
formality — and a reminder to treat "tests exist" and "tests run
automatically on every change" as two separate claims going forward, even
now that the gap above is closed.

**Milestones 6 and 7 are marked "(core)"** — PLAN.md explicitly scopes out,
as deliberately deferred rather than forgotten: for Milestone 6, AI-based
evaluation of candidate answers and resume-inconsistency flagging (blocked
on a real AI model being deployed at Milestone 3, though the gateway
contract to support it already exists), the candidate-facing portal
screens, and persistent storage for file-upload-type question answers; for
Milestone 7, actually sending the `.ics` invite and reminder emails
(deferred to Milestone 12, which is where a self-hosted mail server gets
wired into the compose stack), the candidate-facing self-scheduling UI
(arrives with the Milestone 6 portal), and a cap on how many interviews one
interviewer can be booked into per slot.

Milestone 8 (consent, device pre-check, adaptive STT/TTS interview loop,
and the live candidate HUD), Milestone 9 (sandboxed live-coding workspace:
sandbox-runner, autosaved editor, whiteboard, task discussion), Milestone
10 (RAG FAQ + cross-signal evaluation engine with PDF/Excel export), and
Milestone 11 (dashboard, blind screening, scoring-consistency audit,
tab-focus integrity signals, questionnaire "kits", DSAR export/erasure) are
now delivered and CI-verified, per above — all four have moved out of this
remaining-work table.

Only one milestone remains:

| # | Milestone | Depends on |
|---|---|---|
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

- `apps/web-recruiter` (port 15173): recruiter console — login, pipeline
  board with scored candidate cards, the resume detail Evidence Spine
  (see Milestone 5 section above), (Milestone 9) a Sessions list plus
  an Interview Session detail page: transcript, coding-task creation, a
  live polled read-only view of the candidate's code and run history, a
  bidirectional whiteboard, and discussion, and (Milestone 10) an
  Evaluation section on the resume detail page — generate, view the
  component breakdown and narrative, download PDF/Excel. Still missing:
  requisition browsing, job-description/resume upload screens, MFA prompt
  on login.
- `apps/web-candidate` (port 15174): the candidate portal is now a real
  application (Milestone 8): React Router shell with three steps —
  `Join` (token entry, pre-filled from `?token=`), the consent screen, and
  `PreCheckGate` (live camera preview via getUserMedia, microphone peak-level
  detection through WebAudio with silence classified as degraded rather than
  ok, Web Audio speaker tone with explicit "I heard it" confirmation, and a
  genuine connection sample measuring healthz round-trip plus openapi.json
  throughput) feeding an orchestrating `Interview.tsx` that renders the live
  HUD for active sessions: status chips, elapsed timer, topic progress spine,
  question card with gateway-backed read-aloud (`speak` → WAV blob playback),
  typed-text or recorded-audio answering (MediaRecorder → base64 → gateway
  STT), transcript drawer, and an end-session control. An Interview/Workspace
  tab switch (Milestone 9) sits alongside the Q&A flow — the Workspace tab
  holds an autosaving code editor with a run button and stdout/stderr/exit-code
  display, a canvas whiteboard synced with the interviewer, a discussion
  thread, and (Milestone 10) an FAQ tab answered by retrieval-grounded
  generation over the recruiter's FAQ documents. Terminal states render
  dedicated completed/declined/aborted screens. All traffic flows
  same-origin through the Vite dev proxy; no external calls.

  - Loads session state by token on mount and switches on `status` to
    render the right screen: a consent gate (`pending_consent`), the
    `PreCheckGate` component from `PreCheck.tsx` (`consent_granted`/
    `precheck_passed`), the live interview HUD (`active`), or a plain
    closing message for `completed`/`declined`/`aborted`.
  - The consent gate shows the versioned consent statement returned by the
    API and calls `submitConsent`, refetching state afterward — declining
    is a dead end, matching the backend's terminal-state design.
  - The live HUD is fully built out: an elapsed-time clock, a topic
    progress bar, a "Read aloud" button that calls the `/tts` endpoint and
    plays the returned audio, a text box for typed answers, and a real
    microphone recorder (`MediaRecorder`) with "Record answer" / "Stop &
    send recording" that posts the captured audio to `/turns` as base64 —
    so both answer paths exercised by the backend's integration test
    (typed and spoken) are already reachable from real UI. A collapsible
    transcript log tracks every answer given so far, and an "End interview"
    button calls `finishInterview`.

  Routing is now fully and cleanly wired: `App.tsx` owns a `BrowserRouter`
  directly (an earlier intermediate version wrapped it in `main.tsx` with
  a `HashRouter` instead; that has been consolidated), rendering `Join` at
  `/` and `Interview` at `/interview`, with an unknown-path redirect back
  to `/`. `react-router-dom` is now correctly listed in
  `apps/web-candidate/package.json`'s dependencies and the workspace
  lockfile has been updated to match. `vite.config.ts` now also proxies
  `/api` requests from the dev server through to the backend on port
  18000, matching the `API_BASE = "/api"` constant already used in
  `api.ts`. With this, `apps/web-candidate` is a complete, internally
  consistent application: a candidate can follow their invitation link,
  give or decline consent, pass a real equipment check, and complete a
  live, adaptive interview by typing or speaking answers, entirely through
  working screens wired to the real backend API described earlier in this
  document. Nothing about this app is still a stub.

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
