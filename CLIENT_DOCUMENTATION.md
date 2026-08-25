# AIVA — Project Documentation

**Prepared for:** Client review
**Last updated:** 2026-08-25
**Status:** Milestones 1 through 8 delivered and verified with automated
end-to-end tests, including a complete, working candidate interview
experience (invitation link through live adaptive interview). See the
"Remaining roadmap" and verification-accuracy sections below for the small
number of open items and what is still ahead.

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
  two-factor login flow. This test was not yet included in the automated
  pipeline that gates every code change when it was first written; that gap
  has since been closed, and this test (along with the equivalent
  end-to-end tests for resume handling, questionnaires, and interviews,
  described further down) now runs automatically on every change, the same
  as the rest of the platform's safety net.
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
  checks and a practice room will be available before any real interview.
  Behind the scenes, the code that will let this app talk to every step of
  the interview process described above (checking status, giving consent,
  running the equipment check, starting, answering by text or voice, and
  finishing) has now been written and is ready to use, and the first real
  screen is now being built on top of it: a page where a candidate pastes in
  (or automatically receives, via their invitation link) their personal
  interview token to begin the process, described as "Step 1 of 3." Helper
  code for working with microphone recordings in the browser has also
  appeared.

  A second real screen, described as "Step 2 of 3," is a genuinely working
  equipment check: it turns on the candidate's camera and shows a live
  preview, listens to the microphone for a few seconds to confirm it is
  picking up sound, plays an audible test tone the candidate confirms they
  heard, and measures the candidate's connection speed and responsiveness —
  all in the browser, with a clear statement that nothing is being recorded
  yet. The candidate cannot proceed until all four checks pass. This
  matches the strict, fail-closed equipment check described earlier in this
  document and is not just a visual mock-up — it produces the same
  structured report the backend expects.

  The piece that ties everything together has also now been built: a
  screen that shows a candidate their recording-consent statement and
  records their decision, then automatically moves them through the
  equipment check and into a fully working live interview experience — a
  timer, a progress indicator showing how many topics remain, a "read the
  question aloud" button, a text box for typing an answer, a genuine
  microphone recording button for speaking an answer instead, and a running
  log of everything answered so far. A candidate can also end the interview
  early if needed. In other words, every step described earlier in this
  document as a design goal — consent, equipment check, live adaptive
  interview, spoken or typed answers — now has real, working screens behind
  it, not just the plan for them.

  These screens are now fully connected into one working flow a candidate
  can click through end to end, starting from their personal invitation
  link: giving or declining consent, passing a real equipment check, and
  completing a live interview by typing or speaking answers. The small
  technical piece flagged in the previous update to this document (a
  missing item in the project's dependency list) has been resolved. The
  candidate-facing application is now functionally complete.
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
  been formally migrated to include all of this (see below), and this has
  since been proven to work end-to-end against a real, running database
  (see the note further down about this test now running automatically on
  every change).
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
- Work on Milestone 3 (the AI gateway) has begun. Two design decisions stand
  out as directly relevant to trust in the system's output:
  - **Every AI-generated judgment must cite its evidence.** The system is
    built so that a score or extracted fact can never exist without a
    confidence level and a pointer back to the specific piece of the
    candidate's own material it came from. This is enforced as a hard rule in
    the code itself, not just a guideline, and is the foundation for what the
    team calls the "Evidence Spine" — the ability to trace any AI decision
    back to its source, planned for the recruiter console.
  - **The scoring instructions given to the AI model explicitly forbid
    guessing.** The first real prompt (for scoring a candidate against a job
    requirement) instructs the model to score only what the candidate's own
    documents and statements actually support, to always cite specific
    evidence, and to never infer things like emotion, personality, or
    confidence level from indirect signals. This is a deliberate anti-bias
    and anti-hallucination safeguard built into the system from the start,
    not added as an afterthought.
  - The gateway can currently run in two modes: a "mock" mode that produces
    realistic, consistent test results without needing any AI hardware
    (useful for building and testing the rest of the system now), and a real
    mode that will call the actual local AI model, with technical safeguards
    that force the model to respond only in the exact expected format and
    reject anything that doesn't match. Every result records exactly which
    prompt version, backend, and model produced it, for full traceability.
  - This service now runs on its own and has a working set of functions
    (checking a candidate against a job requirement is one working example,
    currently using the test/mock mode), verified by automated tests showing
    it produces consistent, repeatable results. It is now part of the same
    containerized system as the main application (started together via the
    same one-command startup), though the two are not yet connected to each
    other — they currently run side by side without talking to one another.
  - A first, small set of "golden" test cases has been established: known
    inputs with automated checks that the AI gateway's output stays
    schema-valid and, crucially, exactly repeatable given the same input.
    This now runs automatically as part of the same quality gate that checks
    every other proposed code change — the beginning of the ongoing
    evaluation process that will be used to catch quality regressions before
    they reach production.
  - A bug that would only surface once the AI gateway ran inside its proper
    container (not on a developer's own machine) has since been found and
    fixed: the service was looking for its instructions in the wrong
    location once packaged, which would have made it unable to find any of
    its prompts in a real deployment despite working fine locally. This is
    exactly the kind of gap automated testing against the real container
    (see above) is designed to catch.
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

The project's plan (`docs/PLAN.md`) is maintained as a running status ledger.
As of this update, it lists three milestones as delivered:

### Delivered

- **Milestone 0 — Foundation and air-gap enforcement**: infrastructure,
  tooling, and the three-part air-gap enforcement approach described in
  Section 2.
- **Milestone 1 — Design system**: the visual foundation and component
  library described in Section 4.
- **Milestone 2 — Authentication, access control, data isolation, and audit
  trail**: everything described in Section 4 regarding accounts, roles,
  organization data isolation, and the tamper-evident audit log, plus a first
  working API for managing organizations, departments, and job requisitions.
- **Milestone 3 — AI gateway**: the evidence-citation contract, anti-bias
  prompt design, and the mock/real backend switch described in Section 4 are
  now marked complete, verified against a mock (simulated) AI model. The
  connection to a real, running AI model is intentionally deferred until
  the necessary GPU hardware is available — this was always the planned
  scope for this stage, not a shortfall. When that hardware is in place, the
  team expects to swap in the real model without changing how the rest of
  the system talks to this service.

**A note on verification accuracy — update**: earlier versions of this
document reported that the project plan's claims of automated, full-pipeline
verification for Milestones 2, 4, 6, and 8's core security/business-logic
tests were ahead of what the pipeline configuration actually showed. As of
this update, that gap has been directly re-checked and is now closed: all
four of those milestones' full, real-world rehearsal tests (covering login
security, resume-to-score matching, questionnaire invites, and the complete
interview session lifecycle) have been confirmed to run automatically on
every single code change, not merely to exist. This document now defers to
that directly-observed, current pipeline state.

Two narrower gaps noted previously remain open, and the project plan does
not claim otherwise: Milestone 5's one new backend piece (the endpoint that
lists candidates for a role) still has no automated test at all yet, not
merely one that exists but isn't wired in; and Milestone 7 (scheduling)
still has no full real-world rehearsal test of its own, relying instead on
smaller, focused tests. Neither gap indicates missing feature work — both
areas are built and function correctly — only that their automated safety
net is narrower than the rest of the platform's.

This kind of gap turned out not to be purely hypothetical while it existed.
While building a later milestone, the development team discovered that the
database permission setup for the questionnaire feature (Milestone 6) and
the scheduling feature (Milestone 7) was incomplete: the account the running
application actually uses day to day was never granted permission to write
to those tables. In practice, this means that in a real deployment, every
attempt to save a questionnaire response or book an interview slot would
have been rejected by the database, despite every automated test for those
features passing. This is precisely the kind of problem a full, live
rehearsal is meant to catch, and it went unnoticed until that rehearsal
actually happened for a later milestone — before the pipeline gap above had
been closed. It has since been fixed with a proper, tracked database
correction, and remains a good concrete example of why closing testing gaps
matters in practice, not just as a formality, even now that this particular
gap is resolved. Separately, an actual pipeline failure was investigated
during an earlier update: the AI gateway was looking for its instructions in
the wrong location once packaged into its deployment container (see Section
4) — that specific issue has since been fixed.

- **Milestone 4 — Resume ingest and matching**: the backend can now read
  PDF and Word resumes and pull out specific facts — email, phone number,
  LinkedIn profile, technical skills, years of experience claimed, and name.
  Every single fact extracted is tied back to exactly where it appeared in
  the original document (which page, and the surrounding sentence), so a
  recruiter can always verify a claim against the source rather than taking
  the system's word for it — the same "always show your work" principle
  used for AI-generated judgments (Section 4) applied to plain data
  extraction as well.

  A more important design decision is visible here too: **objective, checkable
  facts about a candidate — does the resume mention a required skill, does
  the candidate claim enough years of experience — are decided by ordinary,
  predictable computer logic, not by the AI model.** This is a deliberate
  choice made explicit in the code itself. The AI is reserved for things
  that genuinely require judgment; anything that can be checked mechanically
  is checked mechanically, which makes that part of the system's behavior
  fully predictable and auditable rather than dependent on an AI's
  interpretation.

  The scoring model that ties everything together has also been built. It
  makes the same principle explicit at a higher level: **the AI model is
  never allowed to do the math or make the final call.** The AI's only job
  is to produce individual, evidence-backed judgments on genuinely
  subjective dimensions (for example, how well a candidate's communication
  comes across); combining those judgments into a final score and a
  recommendation (reject / hold / shortlist / highly recommended) is done by
  fixed, published weighting rules that a client organization can configure
  themselves. Every individual scoring result is also permanently
  fingerprinted, so it can be exactly reproduced and re-verified later if a
  hiring decision is ever questioned. The corresponding database structure
  for storing job descriptions, resumes, extracted facts, an organization's
  chosen scoring weights, and every scoring run has been built, with the
  same organization-level data isolation used everywhere else in the system.

  **This has now become the platform's first genuinely complete, working
  feature**, reachable as a working API (not yet through either web
  application's screens, but fully functional and testable): a recruiter can
  post a job description, upload a resume, and request an evaluation — the
  system extracts the candidate's details, checks the objective requirements
  in code, asks the AI for judgment on the subjective dimensions (currently
  the safe test/mock version of the AI, not a live model), combines
  everything into a score and a recommendation, and stores a permanent,
  reproducible, evidence-linked record of exactly how that result was
  reached. Duplicate resume uploads are automatically detected and rejected.
  This is the first time any part of the system performs the platform's
  actual core purpose end to end, rather than only supporting infrastructure
  around it. A thorough automated test proves the entire flow above works
  correctly, including that requesting the same evaluation three times in a
  row produces an identical result each time. Like the equivalent test for
  Section 4's security features, this test currently runs on demand rather
  than automatically on every code change — the same easily-closed gap noted
  above.
- **Milestone 5 — Recruiter console**: the recruiter
  console has moved from a design-system preview to real, working screens
  connected to the live backend: a sign-in page, a candidate pipeline view
  (every uploaded resume for a role, with its score and recommendation,
  sortable and searchable), and — most notably — a candidate detail page
  built around a new visual component the team calls the "Evidence Spine."
  This turns the traceability principle described throughout this document
  into something a recruiter can actually see and click through: every
  extracted fact and every AI-generated judgment appears as a point on a
  single scrollable timeline, and clicking any point reveals the exact
  sentence in the candidate's resume (or the AI's exact reasoning) that it
  came from. This is the first piece of the actual product a recruiter would
  recognize as the finished experience, even though it is still narrow (no
  way yet to browse open roles or upload a resume from the screen itself —
  those still require the API directly, and only the recruiter-facing app
  has been touched so far, not the candidate-facing one).
- **Milestone 6 — Candidate questionnaires (core delivered)**: recruiters can
  now build a custom questionnaire for a role (multiple
  question types: multiple choice, yes/no, rating, short and long written
  answers, file upload) and invite a specific candidate to complete it by
  email, without requiring the candidate to create an account. The
  invitation is a secure link built the same way session security works
  elsewhere in the system: the candidate holds a secret token, and only its
  cryptographic fingerprint is ever stored, so the actual secret can't leak
  even from a database breach. A candidate's answers are saved as they go
  (so nothing is lost if they leave and come back), every save is kept in a
  history rather than overwriting the last one, and final submission is
  blocked with a clear list of what's missing if any required question
  hasn't been answered. This is now connected to the running application —
  a thorough automated test proves a full real-world flow works correctly,
  including confirming that an invitation genuinely cannot be reused once a
  candidate has submitted it. This is not yet connected to either web
  application's screens, so it can only be used through the API directly
  today. This is the "core" scope: the project plan explicitly and
  deliberately sets aside two things for later within this same milestone
  rather than treating them as done — AI-assisted evaluation of a
  candidate's written answers (which needs a real AI model connected, not
  the current test/mock one) and the candidate-facing screens themselves.
- **Milestone 7 — Scheduling (core working)**: interview scheduling moved
  from initial logic to a fully working feature within the same update.
  Recruiters can generate a set of bookable interview time slots from their
  availability, built correctly around time zones and daylight saving time
  changes from the outset (proven with tests specifically covering the two
  classic daylight-saving failure cases, not just the ordinary case), list
  those slots, and book one for a specific candidate. Booking a slot
  produces a ready-to-use calendar invite file (the standard format used by
  Outlook, Google Calendar, and similar tools), generated entirely locally
  without relying on any external calendar service, consistent with the
  air-gap requirement. What's still missing: that calendar invite is not
  actually emailed to anyone yet — sending it, and any reminder emails, is
  the one piece of this milestone's originally intended scope that remains
  unbuilt. This is reachable through the API, but no web app screen exists
  for it yet.
- **Milestone 8 — Live interview experience (core working)**: the
  candidate portal is now a real application. A candidate follows their
  personal invitation link, sees exactly what will happen to their data and
  gives (or declines) explicit recording consent — declining ends the
  process immediately, and the system refuses to start any interview without
  that consent. Next they run a genuine equipment check in their own browser:
  a live camera preview, a microphone test that listens for actual voice
  input, a speaker test tone they must confirm hearing, and a connection
  quality sample. Only then does the guided interview begin: the system asks
  structured questions derived from the gap between the job's requirements
  and the candidate's resume, with automatic follow-up questions when an
  answer seems thin. The candidate can type answers or speak them; spoken
  answers are transcribed locally by the speech system described above, and
  every question can be read aloud by the voice-synthesis system. Both the
  questions themselves and the decision of when to dig deeper are made by
  plain, auditable code rather than the AI model, so any interview can be
  replayed to verify it would unfold identically — the AI's role stays
  confined to later evaluation with cited evidence, as everywhere else in
  the platform. Everything is proven end-to-end by automated tests running
  against the full live system. Still deliberately deferred: connecting the
  video-conferencing layer itself (needs dedicated media infrastructure),
  switching on the real speech models (needs the GPU deployment), and
  identity verification / proctoring signals (planned for the integrity
  milestone).

### Remaining roadmap

| Milestone | What it delivers | Depends on |
|---|---|---|
| M9 | The sandboxed technical-assessment environment: code editor, whiteboard, screen share | M8 |
| M10 | An internal FAQ assistant, the evaluation engine, and exportable reports (PDF/Excel) | M9 |
| M11 | Recruiter dashboards, blind/bias-reduced screening, hiring-integrity signals, data-subject request (DSAR) tooling | M10 |
| M12 | Load testing, a penetration-test pass, data-retention automation, and a Kubernetes deployment package (Helm) | M11 |

This also answers one of the earlier open questions: the intended production
deployment target is a **Kubernetes cluster** (via a Helm chart, planned for
Milestone 12), consistent with the client-managed, on-premise/air-gapped
requirement.

Other items explicitly tracked as still open: local testing on the
development machine is currently blocked on a pending Docker installation
(the system is proven to work via the automated pipeline in the meantime);
formal test-coverage requirements and the AI evaluation benchmark content
begin at Milestone 4; and encryption-at-rest for stored files is deferred to
Milestone 12 as previously noted.

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

- Data retention and deletion policy for candidate data.
- Precise hardware/GPU requirements for the AI models once Milestone 3 begins.

---

*This document is regenerated/updated automatically as the codebase evolves. If
something here looks out of date, check the "Last updated" date above against the
latest commits.*
