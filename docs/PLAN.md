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

## Remaining milestones

| # | Milestone | Depends on |
|---|---|---|
| M9 | Sandbox runner, editor, whiteboard, screen share, task discussion | M8 |
| M10 | RAG FAQ, evaluation engine, report + PDF/Excel export | M9 |
| M11 | Dashboard + blind screening, bias audit, integrity signals, kits, DSAR | M10 |
| M12 | Load test, pen-test pass, retention jobs, Helm chart | M11 |

## Known open items carried forward

- Local Docker Engine install in WSL pending operator action; compose stack is
  proven via CI integration job meanwhile.
- Coverage thresholds and golden-set content begin at M4 when scoring logic exists.
- MinIO server-side encryption wires into KES/Vault at production hardening (ADR-008).

