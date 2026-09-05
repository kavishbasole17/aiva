# PLAN — Status Ledger

## Delivered and CI-verified

### Milestone 0 — Foundation
Monorepo scaffold, healthchecked compose stack (Postgres 16 + pgvector/pg_trgm,
Redis 7 AOF, MinIO + bucket init), API skeleton with liveness/readiness probes,
fail-closed settings, strict CSP middleware, egress enforcement script (negative
test proven), GitHub Actions pipeline. All six CI jobs green.

### Milestone 1 — Design system
`packages/ui`: tokens.css with atigro.com-sampled brand values (ADR-014), fluid
type scale, motion tokens + spring constants, ThemeProvider (dark/light),
`prefers-reduced-motion` collapse, Reveal/PageStagger one-shot scroll primitives,
ScoreRing spring arc, Button/Input/Textarea/Card/Badge/EmptyState/Skeleton/Field,
self-hosted OFL variable fonts via @fontsource (ADR-016). Both web apps consume
the system; Tailwind 3.4 driven entirely by CSS custom properties. Lint/typecheck/
build green locally and in CI.

### Milestone 2 — Auth, RBAC, RLS, audit, org CRUD
Argon2id passwords, JWT access tokens, refresh-token rotation with family-wide
reuse detection, TOTP MFA enrollment/activation/login gating, six-role RBAC with
per-endpoint permission dependencies, Postgres RLS (FORCE) scoped to organization
with bootstrap-safe policies, app/migration DB role split, org/department/
requisition/staff CRUD, hash-chained append-only audit log with verification
endpoint. Proven in CI integration job: two-org RLS isolation, full role×endpoint
authorization matrix, refresh replay revocation, MFA flow, chain integrity.

### Milestone 3 — AI gateway (mock-verified; GPU inference deferred to deployment)

`services/ai-gateway`: stable typed contract (`DimensionScore`,
`ResumeFieldExtraction` — every judgement carries rationale, confidence, and
mandatory cited span ids per constraint 8.1), versioned prompt registry
(SHA-truncated prompt versions returned with every response), pluggable backends:
deterministic mock (schema-filling, seed-keyed, CI-safe) and vLLM backend using
`guided_json` constrained decoding with temperature 0 and pinned seed so schema-
invalid output is impossible by construction. Golden-set eval harness
(`packages/eval`) runs against the live container in CI: schema validity +
determinism asserted per case. Gateway quality gates green (ruff/black/mypy-strict/
bandit/pytest); all 7 CI jobs green.

Deferred to GPU deployment: pulling Qwen2.5-14B-AWQ weights into the runtime image,
the §13 `--network none` end-to-end interview proof, and real-model eval thresholds.
The backend interface does not change when those land.

### Milestone 4 — Resume ingest, matching, weighted scoring

Span-preserving extraction (PDF via pymupdf, DOCX via python-docx, TXT) where every
field resolves to page number + char offsets + literal source quote — verified by a
test that re-slices every span and compares against its value. Deterministic
regex/lexicon extraction for email/phone/LinkedIn/skills/years/name; multi-page
page-mapping test. Matching checks are computed in code only (skill presence,
preferred coverage, stated-vs-required years). Versioned WeightProfile objects with
normalized shares and threshold bands → auto_reject/hold/shortlist/highly_recommended;
scoring runs persist dimension payloads with per-dimension evidence refs (deterministic
checks vs. gateway judgements carrying prompt-version+model citations) plus a
run_fingerprint — CI proves byte-identical fingerprints across repeated runs
(determinism gate). Duplicate-resume rejection by content hash, 10MB cap, magic-byte
sniffing. Integration job exercises upload → JD → profile → score roundtrip against
the live stack including containerized gateway.

### Milestone 5 — Recruiter console shell + Evidence Spine v1

Auth-gated React Router shell (login → protected routes, token store, sign-out).
Pipeline page per requisition: scored candidate cards with verdict badges,
score/name sorting and text filtering via FLIP spring reordering (motion `layout`),
designed loading/empty/error states throughout. Resume detail page renders the
Evidence Spine v1 from packages/ui — a scroll-linked drawn rail where each node is
a score or extracted field; expanding a node reveals the literal source quote plus
page/offset/confidence/extractor metadata, and LLM-judged dimensions cite their
prompt-version+model evidence refs. Vite dev proxy keeps API traffic same-origin.
Backend gained `GET /requisitions/{id}/candidates` (resume rows joined to latest
scoring run). All 7 CI jobs green.

Deferred within M5: Playwright E2E + axe audit wiring, 60fps trace capture,
Lighthouse runs, command palette, saved views (M11/M12 hardening gates).

### Milestone 6 (core) — Questionnaires, invites, autosave

Questionnaire builder entities with validated question schemas (typed questions,
unique ids, multiple-choice option rules), single-use SHA-256-tokenised candidate
invites (raw token shown once at creation), resumable autosaved responses that
append every save to a retained history snapshot list, deterministic
required-answer completeness enforcement on submit, staff-facing response listing.
Public endpoints are token-scoped; completed/expired links return 409/410.
All 7 CI jobs green.

Deferred within M6: AI evaluation of answers + resume-inconsistency flags (needs M3
model deployment for meaningful output — the gateway contract exists), candidate
portal UI pages, file-upload question storage.

### Milestone 7 (core) — DST-correct scheduling + local .ics

Pure-function slot generation driven by recruiter availability rules (working-hours
window, duration, buffer, weekend exclusion, blackout dates) computed in the
recruiter's timezone via zoneinfo with PEP-495 round-trip detection of nonexistent
wall times; emitted as UTC and deduplicated across regeneration runs. Unit tests
cover America/New_York spring-forward (2:00–2:30 gap slots absent, durations intact),
fall-back ambiguity (no duplicate wall-clock starts), weekend/blackout exclusion,
buffer arithmetic, inverted ranges, non-UTC zones. Local RFC-5545 `.ics` generation
with proper escaping and UTC formatting replaces any calendar API per §3. Booking
endpoint flips slot status with conflict rejection and emits the invite file.
All 7 CI jobs green.

Deferred within M7: SMTP delivery of `.ics` invites and T-24h/T-1h reminders
(requires self-hosted Postfix in compose — wired at M12 hardening), candidate-facing
self-select UI (arrives with portal), interviewer-per-slot caps.

### Milestone 8 (core) — Interview sessions: consent, device pre-check, adaptive STT/TTS loop, HUD

`apps/api`: token-gated interview sessions (raw join token shown once at creation,
SHA-256 stored — the questionnaire-invite discipline) with a fail-closed lifecycle
pending_consent → consent_granted → precheck_passed → active → completed/declined/aborted.
Consent is versioned: the candidate must accept the exact current statement version,
declining is terminal, and no question is ever served before granted consent plus a
passing device report. Pre-check validation (`app/precheck.py`) rejects stale suite
versions, unknown statuses, missing/degraded required devices and unverified or
sub-minimum connections. The adaptive loop (`app/interview_engine.py`) is pure code:
question plans are fingerprinted from JD-vs-resume gaps (missing required skills,
verified skills, stated-vs-required years), thin answers spend one scripted probe per
topic before advancing, and transcripts replay deterministically. Turns persist with
STT confidence/model/audio-hash attribution; staff endpoints expose session lists and
full transcripts. Migration 0006 adds RLS-forced interview tables; migration 0007
backfills `aiva_app` grants that migrations 0004/0005 omitted (a latent privilege gap
found by this milestone's integration flow).

`services/ai-gateway`: speech media behind stable typed contracts — `/v1/stt` and
`/v1/tts` with pluggable providers (deterministic mock transcriber/speaker proven in
CI; faster-whisper/Piper classes raise clear not-deployed errors). Mock TTS emits real
PCM16 WAV bytes; mock STT returns hash-seeded synthetic transcripts with WAV-header
duration parsing.

`apps/web-candidate`: the portal is now real — join-by-token, consent screen, browser
device pre-check gate (camera preview, mic level detection, speaker tone confirmation,
latency+throughput sample), and the live HUD: status chips, elapsed timer, topic
progress spine, question card with gateway-backed read-aloud, text or recorded-audio
answering, transcript drawer, and end-session control. React Router wired; Vite proxy
keeps traffic same-origin.

Proven in CI integration job: full lifecycle against the live stack including
containerized gateway — gates reject early start/failing pre-check/stale consent,
consent-denial is terminal, audio turn round-trips through STT, engine closes within
budget, terminal state rejects mutation, staff detail shows attributed transcript.
The integration job now also runs the previously-unwired auth/resume/questionnaire
lifecycle tests. All quality gates green.

Deferred within M8: LiveKit room infrastructure + client SDK tokens (needs media
infra in compose — interface unchanged when it lands), faster-whisper/Piper weights
(GPU deployment), InsightFace identity verification and MediaPipe proctoring signals
(M11 integrity work), §13 `--network none` proof.

### Milestone 9 — Live-coding workspace: sandbox runner, editor, whiteboard, task discussion

`services/sandbox-runner`: a new microservice executing candidate-submitted Python/
JavaScript under process-level isolation — dedicated unprivileged `sandbox` account
(setuid-dropped into per execution, never the server's own uid, so RLIMIT_NPROC and any
escape stay scoped away from the service itself), POSIX rlimits (CPU seconds, address
space, process count, open files, output size), a routeless network namespace via
`unshare --net`, ephemeral per-run temp directories, and a hard wall-clock timeout that
kills the whole process group. Fails closed if `unshare` is unavailable rather than
degrading to an unisolated run. See ADR-019 for the full isolation design and its honest
limits (process-level, not container/VM — a hardened runtime is deferred to M12).

`apps/api`: migration 0009 adds five session-scoped, org-scoped, RLS-forced tables
(`coding_tasks`, `code_snapshots`, `code_executions`, `whiteboard_strokes`,
`discussion_messages`) with the same bootstrap-safe policy as interview_sessions.
`routers_workspace.py` gives staff (JWT) task creation plus read/annotate access to
everything, and gives the candidate (raw token, same discipline as the interview/
questionnaire flows) autosaved code editing, sandboxed run requests proxied to
sandbox-runner, whiteboard strokes, and task discussion — candidate writes gated to an
ACTIVE session, reads open through any non-terminal state. Screen share is a stable
public endpoint that returns 501 rather than a fake success (no WebRTC/LiveKit
infrastructure in this compose stack — same mock-now/hardened-at-deployment precedent as
ADR-017's STT/TTS backends, not a new deferral pattern).

`apps/web-candidate`: a Workspace tab alongside the interview Q&A — autosaving code editor
with a run button and stdout/stderr/exit-code display, a canvas whiteboard synced with the
interviewer, and a discussion thread. `apps/web-recruiter`: a new Sessions list page and
Interview Session detail page — transcript, task creation, a live (polled) read-only view
of the candidate's code and run history, a bidirectional whiteboard, and discussion.

Proven end-to-end against the live stack (real Postgres/RLS, real ai-gateway, real
sandbox-runner): task creation → candidate autosave → sandboxed run → staff sees the
result, whiteboard strokes from both sides render together, discussion round-trips both
ways, cross-org staff access 404s, and candidate writes reject with 409 once the session
is terminal (`tests/test_integration_workspace.py`). Sandbox isolation itself is unit-
tested directly: timeout kills an infinite loop, RLIMIT_AS stops an unbounded allocation,
a real socket connect attempt from inside the sandbox is confirmed blocked by the network
namespace, PID-namespace isolation is confirmed by reading back the sandboxed process's
own pid (1, not the host would-be pid), and the per-run uid pool is proven to never hand
out the same uid to two concurrent runs — not just assumed. All quality gates green
(ruff/black/mypy --strict/bandit/pytest) on both apps/api and the new
services/sandbox-runner.

A security review run against this diff before considering M9 done caught a real gap in
the first cut: every execution setuid-dropped into the *same* fixed sandbox account, which
meant the "ephemeral per-run temp directory" isolation claim didn't actually hold under
concurrency — any run's code could list `/tmp`, find another live run's directory (shared
uid, world-listable base-image `/tmp`), and read or overwrite it. Fixed via `UidPool` (a
distinct uid per concurrent execution, never shared, acquired/released around each run)
plus PID-namespace isolation (`unshare --pid --fork`, closing the matching `/proc`
visibility gap) — see ADR-020. Same discipline as the `0007`/`0008` grants-backfill
migrations found during M8: catch it, fix it forward, write down what was actually wrong
and why the fix is complete, not just that a fix happened.

Deferred within M9: a real-time collaborative editor (CRDT/OT) — the editor uses debounced
autosave + poll, same as M6's questionnaire autosave, not live keystroke sync; screen share
backend (WebRTC/LiveKit, ADR-019); hardened sandbox runtime (gVisor/Firecracker/nsjail,
M12).

### Milestone 10 — RAG FAQ, evaluation engine, PDF/Excel export

`services/ai-gateway`: a new `/v1/embed` endpoint behind an `EmbeddingProvider` interface —
`MockEmbedder` (deterministic, hash-seeded, L2-normalized 384-dim vectors) now,
`SentenceTransformerEmbedder` deferred to GPU deployment, same mock-now/hardened-later
split as ADR-017's STT/TTS backends. Only the embedding *model* is mocked — retrieval is
real: `apps/api` migration 0010 adds `faq_documents` with a genuine pgvector column and an
ivfflat cosine-similarity index, and `routers_faq.py`'s candidate-facing `ask_faq` runs an
actual `ORDER BY embedding <=> :query` search, then feeds only what retrieval found into a
new `faq_answer` gateway prompt (`FaqAnswer` response model, same citation discipline as
every other judgement). Staff write FAQ documents; the candidate (raw token, same
discipline as interview/workspace endpoints) asks questions from within the interview
Workspace tab.

`apps/api`: `evaluation_engine.py` deterministically aggregates resume score, questionnaire
completion, interview completeness, and coding-task pass rate into one weighted verdict —
same "arithmetic and thresholds live only in application code" rule `scoring.py`
established; the gateway-backed `evaluation_summary` narrative is additive-only and
degrades gracefully (a persisted report keeps its full deterministic verdict even if the
gateway is unreachable when generated). `report_export.py` renders PDF (reportlab) and
Excel (openpyxl) straight from the persisted `EvaluationReport.payload` snapshot, streamed
on demand from new staff-only export endpoints — see ADR-021.

`apps/web-candidate` gained an FAQ tab in the interview Workspace; `apps/web-recruiter`
gained an Evaluation section on the resume detail page (generate, view component
breakdown/narrative, download PDF/Excel).

Proven end-to-end against the live stack (real Postgres/pgvector, real ai-gateway):
`test_integration_faq.py` proves retrieval actually returns relevant documents and degrades
gracefully with zero FAQ documents; `test_integration_evaluation.py` proves every component
populates from real data, PDF/Excel exports have valid file signatures, and cross-org
access to a report 404s. `evaluation_engine.py`'s weighting/verdict-banding is unit-tested
directly (renormalization over missing components, determinism). All quality gates green
(ruff/black/mypy --strict/bandit/pytest) on `apps/api` and `services/ai-gateway`.

Caught during verification, not after: screenshot-testing the new Evaluation panel surfaced
a pre-existing crash in `ResumeDetail.tsx` — `GET .../scoring-runs` (the list endpoint)
never returned `checks`/`dimensions`, but the page's "latest run" selector assumed it did,
throwing on any resume with a scoring run. Fixed by taking the already-newest-first list's
first entry directly rather than filtering on fields the list endpoint never populates.
Unrelated to M10's own code but blocking its verification, so fixed forward rather than
left for a future milestone to rediscover — same "catch it here, fix it here" precedent as
the M8/M9 grants-backfill and sandbox-isolation findings.

### Milestone 11 — Dashboard, blind screening, scoring audit, integrity signals, kits, DSAR

`routers_dashboard.py`: org-wide pipeline aggregates (requisitions by status, scoring
verdict distribution, interview status distribution, questionnaire submission rate,
coding-task pass rate) via plain SQL COUNT/GROUP BY — no candidate-identifying data
crosses this endpoint. `apps/web-recruiter` gained a Dashboard page.

Blind screening: `?blind=true` on `GET /resumes/{id}` and
`GET /requisitions/{id}/candidates` redacts name/email/phone/linkedin field values
(and the resume's own filename/candidate_email) so a first review pass can focus on
skills/experience signal rather than identity — a toggle in `apps/web-recruiter`'s
Pipeline and Resume Detail pages.

Bias audit and integrity signals were both scoped down from PLAN.md's original naming,
deliberately and documented (ADR-023): this system collects no protected-characteristic
data, so a demographic disparate-impact audit isn't implementable responsibly —
`scoring_audit.py` instead checks scoring-pipeline consistency (verdict drift across
identical-input re-runs, missing evidence citations, suspiciously narrow score bands).
Integrity signals ship only what's genuinely real without an ML model: browser-reported
tab-blur/visibility/fullscreen-exit events during an active interview
(`routers_integrity.py`, migration `0012_integrity_signals`) — face/gaze-based
proctoring (InsightFace/MediaPipe) stays honestly deferred to GPU deployment, same as
M8/M9's docs already flagged.

"Kits": scoped to what the schema actually supports cleanly — cloning a proven
questionnaire onto a new requisition (`POST /questionnaires/{id}/clone`). A reusable
coding-task template library would need a new entity (coding tasks are session-scoped,
not requisition-scoped, per M9's schema) and is left for a future pass rather than
half-built here.

DSAR: `routers_dsar.py` gives admin-only staff a full export of every record tied to a
candidate's email, and an erasure path that overwrites (never deletes) the PII-bearing
columns across every table that holds candidate-authored content — migration
`0011_dsar_update_grants` adds a narrowly-scoped UPDATE grant (not DELETE) on the four
append-only tables that needed it, preserving the "evidence rows are never removed"
discipline (ADR-022). A known, documented gap: JSONB evidence payloads that embed
literal resume quotes are not deep-redacted in this pass.

Proven end-to-end against the live stack: `test_integration_m11.py` covers all six
pieces, plus a role-check that non-admin staff are rejected from DSAR export.
`scoring_audit.py` is unit-tested directly (drift/citation/band-width cases). One real
bug caught during verification and fixed forward: the dashboard's coding-task pass-rate
query used `max(uuid)` to find each task's latest execution — Postgres has no such
aggregate function — fixed by joining on `(task_id, created_at)` instead, which is what
"latest" actually means here anyway. A security review of the diff caught two real DSAR
erasure gaps — `ResumeDocument.filename` and `ExtractedFieldRow.source_quote` were left
unredacted alongside the fields that were, and the export endpoint took the candidate's
raw email as a GET query parameter instead of a POST body — both fixed before this
milestone was called done (ADR-022). All quality gates green
(ruff/black/mypy --strict/bandit/pytest, pnpm lint/typecheck/build).

## Remaining milestones

| # | Milestone | Depends on |
|---|---|---|
| M12 | Load test, pen-test pass, retention jobs, Helm chart | M11 |

### Milestone 12 progress — retention jobs (partial; load test/pen-test/Helm chart not started)

`app/dsar_service.py` extracts the candidate-record lookup and PII erasure logic
`routers_dsar.py` already had (behavior-preserving refactor, existing DSAR tests
unchanged) so it can be driven by more than one trigger. `app/retention.py` adds
`run_retention_sweep()`: age-based erasure using that same logic — a candidate is
swept only once every known record (resume, questionnaire invite, interview
session, evaluation report) predates a cutoff, computed from whichever of those
is *most* recent (`latest_activity_at()`), not each row's own age. `POST
/retention/run` (admin-only, same role gate as `/dsar/*`) exposes it, with a new
`AIVA_RETENTION_DAYS` setting (default 730) and a per-call override for a
tighter one-off sweep. See ADR-024 for why this reuses DSAR's erasure path
instead of a new deletion mechanism, and why the trigger is a manual/admin
endpoint rather than a schedule — no worker or Helm CronJob exists yet to hang
a clock off. `test_retention_unit.py` covers `latest_activity_at()`'s "most
recent wins" logic directly; `test_integration_retention.py` proves the sweep
end-to-end against the live stack (a stale candidate is erased, a fresh one is
exempt under the default window, non-admin is rejected) and is wired into the
CI integration job alongside `test_integration_m11.py`.
Not started within M12: load testing, the pen-test pass, and the Helm chart.

## Known open items carried forward

- Local Docker Desktop is now confirmed working on the developer's Windows/WSL
  machine (previously only proven via the CI integration job): `docker compose
  up -d` for postgres/redis/minio/ai-gateway/sandbox-runner, `alembic upgrade
  head`, `uvicorn app.main:app` for the API, and `npm run dev` for both
  frontend apps all run and talk to each other locally end-to-end (verified
  while building the M12 retention slice above). One environment-specific
  wrinkle, not a project issue: pnpm's Windows shim cannot run with a UNC
  (`\\wsl.localhost\...`) working directory, so `pnpm install` and both
  frontend dev servers were run from a native path inside the WSL distro
  instead (a portable Linux Node.js toolchain under `~/.local`, since the
  distro's own Node was missing and `pacman` needs an interactive sudo
  password) — this doesn't affect CI or a normal single-OS dev setup.
- Coverage thresholds and golden-set content begin at M4 when scoring logic exists.
- MinIO server-side encryption wires into KES/Vault at production hardening (ADR-008).

