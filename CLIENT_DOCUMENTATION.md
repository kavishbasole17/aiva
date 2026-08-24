# AIVA — Project Documentation

**Prepared for:** Client review
**Last updated:** 2026-08-25
**Status:** Milestone 0 — Foundation (infrastructure scaffolding in progress)

> This document is maintained alongside the codebase and will be expanded as each
> milestone is delivered. It is intended to give a non-technical-to-moderately-technical
> reader a clear picture of what AIVA is, how it is built, and what is required to run it.

---

## 1. What AIVA Is

AIVA is an **air-gapped AI-powered candidate evaluation and interview automation
platform**. It is designed to run entirely on-premise, with **zero external network
calls at runtime** — every AI model used by the system is served locally rather than
through a third-party cloud API.

This design is aimed at organizations (e.g. in regulated hiring, government, or
security-sensitive sectors) that need AI-assisted recruiting and interviewing without
sending candidate data, transcripts, or evaluation results outside their own
infrastructure.

## 2. Why "Air-Gapped"

A core requirement of this project is that **no candidate or company data ever leaves
the client's own network**:

- No source file is permitted to contain a literal external URL.
- Automated tooling enforces this in two independent, redundant ways: a linting
  rule blocks it while writing frontend code, and a repository-wide scan script
  blocks it for every other file type, checked against an explicit, reviewed
  allowlist of narrow internal-only exceptions.
- Production deployments run under a default-deny network policy — services cannot
  reach the internet unless explicitly permitted.
- All AI models are hosted and served locally rather than called via external APIs
  (e.g. no calls to third-party LLM providers at runtime).
- Secrets and credentials are never committed to the repository; all runtime
  configuration is supplied via environment variables, validated at startup.

This gives the client full data sovereignty and auditability over the entire pipeline.

## 3. Intended System Components

The project is being built as a monorepo with the following planned structure. Items
marked **(planned)** do not exist in the codebase yet — they represent the agreed
build plan, not current functionality.

| Area | Component | Purpose |
|---|---|---|
| Applications | `api` | Backend service (FastAPI) — health checks, readiness, security headers |
| Applications | `web-recruiter` *(planned)* | Recruiter-facing console (React) |
| Applications | `web-candidate` *(planned)* | Candidate-facing interview experience |
| Services | `ai-gateway` *(planned)* | Single internal entry point to all locally-hosted AI models |
| Services | `worker` *(planned)* | Background jobs: resume parsing, scoring, transcription, report generation |
| Services | `sandbox-runner` *(planned)* | Isolated environment for running candidate-submitted code (technical assessments) |
| Shared packages | `ui` *(planned)* | Shared design system / component library |
| Shared packages | `contracts` *(planned)* | Shared data schemas/types between frontend and backend |
| Shared packages | `eval` *(planned)* | Internal test harness for measuring AI evaluation quality/accuracy |
| Infrastructure | Postgres 16 + pgvector | Primary database, with vector search support for AI-driven matching |
| Infrastructure | Redis | Caching and background job queue |
| Infrastructure | MinIO | Local S3-compatible object storage (resumes, recordings, generated reports) |

## 4. Current Progress

As of this update, the project has delivered infrastructure and platform
foundations only; no end-user features exist yet.

### Delivered

- Docker Compose stack defined (Postgres + pgvector, Redis, MinIO, API service)
- Database initialization script (enables `pgvector` and `pg_trgm` extensions)
- Monorepo tooling configured (pnpm workspaces, Node 22+, editor/formatting rules)
- Environment variable template (`.env.example`) covering all current services
- Air-gap / no-egress policy defined at the repository level
- API service: typed, validated configuration layer (`apps/api/app/settings.py`)
  reading and validating all `AIVA_*` environment variables at startup
- API service: `/healthz` (liveness) and `/readyz` (readiness) endpoints, the
  latter actively checking Postgres, Redis, and MinIO connectivity
- API service: structured JSON logging (via `structlog`) for production-grade
  observability
- API service: security-headers middleware enforcing a strict Content-Security-
  Policy (no external connect/script/style sources, reinforcing the air-gap
  policy), `X-Content-Type-Options`, and `Referrer-Policy`
- API service: dependency manifest and quality tooling defined (`pyproject.toml`)
  covering FastAPI, async SQLAlchemy, Alembic for database migrations, and a dev
  toolchain of pytest, ruff, black, strict-mode mypy, and bandit (security static
  analysis)
- API service: the FastAPI application is assembled and runnable locally
  (startup/shutdown lifecycle wired to Postgres/Redis/MinIO). Interactive API
  documentation UIs are deliberately turned off, since those normally pull their
  JS/CSS from a public CDN, a direct instance of the air-gap policy being applied
  in practice, not just stated.
- Database migration tooling (Alembic) is wired up with a baseline migration in
  place, though no data model exists yet, so there is nothing to migrate until
  the first tables are defined.
- The API now builds and runs as a container: a production-style Docker image
  (multi-stage build, runs as a non-privileged user) that can be built against an
  internal package mirror instead of the public internet, in keeping with the
  air-gap requirement. The full local stack (`docker compose up`) now starts
  Postgres, Redis, MinIO, and the API together successfully.
- Automated test coverage for the API includes honest "degraded" reporting when
  a dependency is unreachable, configuration failing closed (the app refuses to
  start with missing or invalid settings rather than falling back to something
  insecure), and security headers being present on every response including
  errors. Tests run quickly against simulated offline dependencies by default,
  with an opt-in mode to run the same tests against the real database, cache,
  and storage. Dedicated tests now also verify the tamper-evident audit trail
  correctly detects tampering, and that the login/session security logic
  behaves correctly (including rejecting expired or forged session tokens). A
  further, more thorough test proves the full security model end-to-end
  against a real running system: correct permissions per role, one
  organization being unable to access or even detect another organization's
  data, automatic detection of a replayed (stolen) session token, the audit
  trail's integrity holding up after real activity, and the complete
  two-factor login flow. This test is not yet included in the automated
  pipeline that gates every code change, so while it exists and is thorough,
  it has not yet been proven to run automatically on every change.
- Recruiter console (`web-recruiter`) scaffolded: React, TypeScript, and Vite,
  with a working application shell. It currently displays a deliberate
  "design system preview" screen showing every shared interface component
  together (score rings, status badges, buttons, form fields, loading
  placeholders) using sample data only — clearly labeled as not real candidate
  data. This is a milestone checkpoint to review the visual foundation, not a
  real application page.
- Candidate-facing app (`web-candidate`) now has a working shell as well,
  also built with the shared component library. It explains that candidates
  only see this portal after being personally invited, that no candidate
  data is stored before that point, and that camera/microphone equipment
  checks and a practice room will be available before any real interview. No
  real questionnaire or interview functionality yet.
- The air-gap policy is now actively enforced, not just documented: an ESLint
  rule automatically fails any frontend code that contains a literal web address
  (`http://` or `https://`), catching accidental external calls before they ship.

- Work on the shared visual design system has begun (Milestone 1): a full set
  of design foundations is defined, including a typography scale, spacing and
  sizing rules, motion/animation timing (with a reduced-motion accessibility
  override), and both a dark and a light color theme, plus a working
  dark/light mode toggle that remembers the user's preference between visits.
  The accent color was deliberately sampled from a reference brand site
  rather than chosen arbitrarily, with an additional, brighter variant added
  specifically to keep small colored text readable and accessibility-compliant.
  A first set of reusable interface pieces has been built on top of this:
  buttons, form fields, cards, status badges, loading placeholders, an empty-
  state layout, smooth scroll-in animations (which respect users'
  reduced-motion accessibility preferences), and a circular score indicator
  clearly intended for showing a candidate's evaluation score in the recruiter
  console. This shared component library is now properly packaged, and the
  recruiter console has started using it (the candidate app has not yet). No
  full pages exist — these are individual building blocks, not finished
  screens.
- The remaining planned parts of the system (shared data contracts, evaluation
  harness, AI gateway, background workers, sandboxed code execution) still
  have only reserved locations in the codebase, with no functionality yet.
- The first real data model has been designed (not yet active in any running
  database): organizations, departments, users, job requisitions, session
  tokens, and audit log entries. Notable design choices already visible:
  - **Six user roles** are defined: administrator, hiring manager, recruiter,
    interviewer, auditor, and candidate — giving a concrete shape to the
    planned access-control model.
  - **Data isolation between organizations** is planned at the database level
    itself (Postgres Row-Level Security), not just in application code — a
    stronger guarantee that one client's data cannot leak into another's in a
    multi-tenant deployment, should the platform ever host more than one
    organization.
  - **A tamper-evident audit trail**: every recorded action is
    cryptographically linked to the one before it, so that any attempt to
    retroactively alter or delete a past audit entry can be detected. This is
    directly relevant to defensibility of AI-assisted hiring decisions under
    scrutiny (e.g. an EEO complaint or an internal review).
  - **Session security**: the plan for login sessions includes automatic
    detection of stolen or replayed session tokens, a standard defense used
    by security-conscious platforms.

  The login/session-security logic itself has also now been built (industry-
  standard password hashing, two-factor authentication, and automatic
  detection of stolen or replayed sessions, as described above, are
  implemented, not just planned), and a full set of authentication endpoints
  is now connected to the running application: organization sign-up, login
  (with two-factor authentication enforced once enabled), session refresh,
  two-factor enrollment, and a "current user" check. Every authentication
  action is recorded in the tamper-evident audit trail. The database has now
  been formally migrated to include all of this (see below), though it has
  not yet been proven to work end-to-end against a real, running database.
- The organization-level data isolation described above is no longer only an
  application-level rule — it is now enforced directly by the database
  itself, in a way that applies even to the database's own administrative
  access. In practice, this means one organization's data being exposed to
  another due to an application bug is significantly harder, because the
  safeguard does not depend on the application getting every query right.
  The application also connects to the database using a restricted account
  rather than a full administrative one, limiting the damage any single
  compromised component could do. This separation is now fully in place: the
  running application always uses the restricted account, and only the
  database-setup process itself uses elevated access.
- Administrators can now directly create accounts for their team (recruiters,
  interviewers, auditors, hiring managers) with an assigned role, separate
  from the organization's initial self-service sign-up.
- The first real business functionality has also landed: an API for managing
  organizations, departments, and job requisitions (job postings), with
  access restricted appropriately by role, cross-organization access
  explicitly blocked, and every change recorded in the audit trail. This is
  the backend counterpart to the recruiter pipeline the console will
  eventually display.
- The audit trail described above is now queryable and independently
  verifiable through the API: administrators and auditors can retrieve the
  full history of actions for their organization, and a dedicated check
  confirms the tamper-evident hash chain has not been broken.
- An automated quality gate now runs on every proposed code change: it checks
  for accidental external network calls, validates the infrastructure
  configuration, lints and type-checks all application code, runs the security
  scanner, runs the automated test suite, and separately boots the entire
  system in a container stack to verify it actually starts up and reports
  itself healthy end to end. Nothing merges without passing all of this.

### Not Yet Started

- Candidate-facing app user interface, AI gateway, and background workers
- AI model integration
- Authentication, data model, and any candidate-facing features

**In short:** the foundation (how services run, talk to each other, and stay
air-gapped) is in place. Feature development has not started.

## 5. How to Run the Current Foundation (technical)

Requires: Docker + Docker Compose, Node.js 22+, pnpm 9.15.0.

```bash
cp .env.example .env
docker compose up -d
scripts/wait_ready.sh
curl http://localhost:18000/readyz
```

This brings up Postgres, Redis, MinIO, and the API service shell. There is not yet a
user-facing application to interact with.

## 6. Roadmap and Verification

A formal project plan (`docs/PLAN.md`) now exists for the current milestone.

### Milestone 0 — Foundation and Air-Gap Enforcement

Marked "delivered, awaiting gate proof": the work is complete and is being
formally checked against its own acceptance criteria before being signed off.
Verification results recorded so far:

| Check | Result |
|---|---|
| Frontend lint, type-check, build | Passed |
| Backend lint (ruff), formatting (black) | Passed |
| Backend strict type-checking (mypy) | Passed |
| Backend security scan (bandit) | 0 issues found |
| Automated test suite | 10 tests passed (2 additional tests require a running live stack and were skipped in this check) |
| Air-gap / no-external-URL scan | 49 files scanned, 0 violations. The scan was also deliberately tested by planting a fake external URL, confirming it correctly fails, and then removing it. |
| Full system startup via Docker | Verified via the automated CI pipeline (not yet confirmed on this local machine) |

### Known upcoming milestones

Referenced elsewhere in the codebase, not yet detailed:

- **Milestone 1**: shared design system / visual component library
- **Milestone 3**: the AI gateway, the single local entry point to all AI models
- **Milestone 5**: the recruiter pipeline view (requisitions and candidates)
- **Milestone 9**: sandboxed execution environment for candidate coding assessments

### Explicitly deferred (not part of the current milestone)

To keep scope honest, the following are intentionally not being worked on yet:
authentication and access control, any real data model beyond an empty database
migration placeholder, visual design work, the AI models themselves and the
gateway that will serve them, real-time video/audio infrastructure for live
interviews (the codebase references **LiveKit**, an open-source video/audio
conferencing platform, as the intended technology), the sandboxed code execution
environment, formal test-coverage requirements, and the content of the AI
evaluation harness.

## 7. Planned AI Capabilities

No AI models are active yet; Milestone 0 is infrastructure only. However, the
development team has already selected a candidate model for each planned
capability, recorded in the codebase's model inventory and subject to a formal
review before any model is actually integrated:

| Capability | What it does | Candidate model |
|---|---|---|
| Reasoning and scoring | The core "judgment" model behind candidate evaluation | Qwen2.5-14B-Instruct (with a smaller fallback model) |
| Semantic search / matching | Powers vector-based matching (e.g. resume-to-role fit) | bge-m3 |
| Resume parsing | Extracts structured candidate information from resumes | spaCy-based, with OCR fallback for scanned documents |
| Speech-to-text | Transcribes interview audio | faster-whisper |
| Text-to-speech | Voice output for the AI interviewer | Piper |
| Identity verification | Confirms the candidate's identity, with explicit consent | InsightFace (face matching) |
| Proctoring | Detects signals relevant to exam/interview integrity | MediaPipe Face Mesh |
| Result re-ranking | Refines and orders evaluation results | bge-reranker-v2-m3 |

All of these are intended to run locally, consistent with the air-gap requirement
described in Section 2. Every model is required to pass a formal review (purpose,
license clearance for commercial use, hardware requirements, accuracy results on
an internal benchmark set, known limitations) before it is integrated — this is a
hard project rule, not a suggestion.

Real-time interview audio/video is planned to be built on **LiveKit**, an
open-source, self-hostable video/audio conferencing platform — chosen so live
interview sessions can also run entirely within the client's own infrastructure.

## 8. Governance and Engineering Documentation

The development team maintains a set of internal engineering documents alongside
this client-facing summary:

- **PLAN** — the build plan and verification evidence for each milestone
- **DECISIONS** — a record of every significant technical decision, including the
  reasoning behind it and the alternatives that were considered and rejected
- **RUNBOOK** — the living operational reference (how to run, configure, and
  verify the system)
- **MODEL CARD** — the AI model inventory described in Section 7 above

One decision recorded there is worth surfacing directly: data-at-rest encryption
for the object storage layer (candidate documents, recordings, generated reports)
is intentionally deferred to the production infrastructure milestone, where
proper encryption key management will exist. This is documented as a deliberate,
temporary gap in the development environment only, not an oversight, and it is
tracked to be closed before production deployment.

## 9. Open Questions / Not Yet Defined

To keep this document honest, the following are not yet visible in the codebase
and should be confirmed with the development team as work progresses:

- Full authentication implementation is still pending, but the underlying
  design is now substantially clear (see Section 4 below): six user roles,
  secure password storage, two-factor authentication, and theft-resistant
  session handling.
- Data retention and deletion policy for candidate data.
- Final deployment target. The production configuration approach (Helm-based
  deployment with secrets from a KMS/Vault system) points toward a
  client-managed Kubernetes cluster, but this has not been explicitly confirmed.

---

*This document is regenerated/updated automatically as the codebase evolves. If
something here looks out of date, check the "Last updated" date above against the
latest commits.*
