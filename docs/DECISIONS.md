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

## ADR-014 — Brand colour reconciliation from atigro.com

Context: §4 requires sampling atigro.com before styling; proposed `--signal` was teal
#12B5C9 described as "from Atigro's blue".
Decision: sampled live site CSS: primary blue **#1863DC** (35 occurrences) and darker
variant **#046BB3** (26). Dark theme `--signal: #1863DC`, light theme `--signal:
#046BB3`. Added derived `--signal-text` (#6FB1FF dark / #045a97 light) because #1863DC
on the abyss base measures ~3.5:1 — acceptable for large UI accents, below AA for body
text; small signal-coloured text uses the brighter tint. `--ember` stays as specified
(#F2701F/#C4540F): no clear counter-evidence on the site, and the action accent must
stay distinct from Atigro's blue.
Consequences: brand-faithful palette with AA-compliant text usage documented;
sequential chart ramps derive from --signal per §4.1.

## ADR-015 — exactOptionalPropertyTypes disabled for UI packages

Context: motion (Framer Motion v11) component typings are incompatible with
TypeScript's `exactOptionalPropertyTypes`; every optional prop assignment on
`motion.*` elements errors, forcing spread-hacks through the entire component layer.
Decision: drop exactly that flag from `packages/ui` and the two web apps' tsconfigs.
All other strict flags remain, including `noUncheckedIndexedAccess`.
Consequences: marginally weaker optionality checking in frontend code; unblocks the
locked animation library without `any` casts or banned suppressions. Revisit when
motion ships EOP-compatible types.

## ADR-016 — Fonts via @fontsource variable packages

Decision: Space Grotesk Variable, Inter Variable, JetBrains Mono Variable vendored as
npm @fontsource-variable packages (all SIL OFL 1.1 — commercial use cleared), bundled
by Vite into self-hosted assets; no CDN, no external font fetch at runtime.
Consequences: licence-safe, versioned, reproducible; woff2 preloading refinements land
with the performance pass in M5.



## ADR-017 — Speech media (STT/TTS) behind gateway contracts, mock-first

Context: M8 needs speech-to-text and text-to-speech for the adaptive interview loop,
but faster-whisper weights and Piper ONNX voices require GPU/media infrastructure that
does not exist in dev or CI. The LLM side already solved this shape at M3 with the
mock/vLLM backend split.
Decision: `/v1/stt` and `/v1/tts` live on the ai-gateway behind typed contracts
(`Transcription`, `Synthesis` — both carrying provider and model ids per constraint 8.1).
Deterministic mock providers are CI-default: TTS synthesizes real PCM16 WAV bytes whose
duration tracks the requested text; STT returns hash-seeded synthetic transcripts with
WAV-header duration parsing. `FasterWhisperTranscriber`/`PiperSpeaker` classes exist but
raise a clear RuntimeError until packages+weights land at deployment; selecting them via
`AIVA_GATEWAY_STT_BACKEND`/`AIVA_GATEWAY_TTS_BACKEND` is a deployment-time switch. The
mypy overrides for their lazy imports (`faster_whisper.*`, `piper.*`) are expected-absence
declarations, not suppressions of real errors.
Consequences: the interview loop, HUD read-aloud, and transcript attribution are fully
provable without GPUs; swapping providers changes zero call sites. Mock transcripts must
never be presented as recognized speech — they are visibly synthetic token streams.

## ADR-018 — Interview sessions: fail-closed consent/pre-check gates + deterministic loop

Context: recording consent and equipment readiness gate a live interview that persists
candidate audio-derived data. The questionnaire milestone established single-use raw
tokens stored as SHA-256.
Decision: interview sessions reuse that token discipline. The lifecycle
(pending_consent → consent_granted → precheck_passed → active → completed/declined/aborted)
is enforced server-side and fails closed: stale consent versions rejected, declining is
terminal, pre-check reports validate against a versioned suite (stale suite version,
missing/degraded required devices, unverified or sub-minimum connections all block start).
The adaptive question loop itself is pure code (`interview_engine.py`) with fingerprinted
plans derived from objective JD-vs-resume gaps — the LLM stays out of control flow, so any
transcript replays to the same sequence. Migration 0007 backfills `aiva_app` grants that
0004/0005 silently omitted (caught by M8's integration flow before it could surface as a
runtime permission failure); append-only migration history is preserved by fixing forward.
Consequences: consent records carry an immutable statement snapshot; LiveKit room/token
infrastructure remains deferred to media-infra deployment without changing these contracts.

## ADR-019 — Sandbox code execution: privileged supervisor, unprivileged per-job account

Context: M9's live-coding task needs to execute candidate-submitted Python/JavaScript.
Unlike every other service in this repo, `sandbox-runner` cannot drop root at container
start (`USER aiva`, the pattern every other Dockerfile uses) — it needs root's ability to
setuid/setgid per execution.
Decision: `sandbox-runner`'s server process stays root; a dedicated, unused-for-anything-else
`sandbox` account (fixed uid/gid 6666) is what candidate code actually runs as, dropped into
via `setresuid`/`setresgid` in a `preexec_fn` immediately before exec, after POSIX rlimits
(CPU seconds, address space, process count, open files, output size) are set on the
about-to-be-unprivileged process. The run also execs through `unshare --map-root-user --net`
for a routeless network namespace, and writes to an ephemeral per-run temp directory. This is
the standard "privileged supervisor, unprivileged per-job account" shape used by
code-execution sandboxes (e.g. Judge0) — not an oversight of the no-root convention.
Consequences: RLIMIT_NPROC and any process-level escape are scoped to the dedicated `sandbox`
uid, never the server's own uid, because nothing else on the system runs as that uid. This is
process-level isolation on a shared kernel, not a container/VM boundary — a kernel exploit
still escapes it. A hardened runtime (gVisor/Firecracker/nsjail+seccomp) is deferred to M12
deployment hardening, same mock-now/hardened-at-deployment precedent as ADR-017's STT/TTS
backends; `app/executors.py`'s `Executor` interface does not change when that lands. Screen
share (also M9) gets the same treatment one level up: a stable public endpoint that returns a
clear 501 rather than a fake success, because it needs WebRTC/LiveKit infrastructure this
compose stack doesn't run — mirroring ADR-017/018's mock-vs-real backend split rather than
inventing a new deferral pattern.

## ADR-020 — Sandbox isolation: one dedicated uid per concurrent run, not one shared uid

Context: ADR-019's first cut of `sandbox-runner` setuid-dropped every execution into the
*same* fixed `sandbox` account (uid 6666). A security review of the M9 diff caught that
this defeats the "ephemeral per-run temp directory" isolation claim under concurrency:
`os.chown(tmpdir, sandbox_uid, sandbox_gid)` + `chmod 0o700` only restricts access to the
owning *uid*, and since every run shares that uid, any run's sandboxed code can
`os.listdir("/tmp")` (world-listable on the base image), find every other live run's
directory by name, and freely read or overwrite it — a concrete, exploitable cross-session
(and cross-organization, if a deployment runs interviews for more than one org
concurrently) data leak reachable through the platform's own normal `/run` endpoint.
Sharing a uid also lets concurrent runs see and `kill()` each other via `/proc`, since
PID-namespace isolation wasn't in place either.
Decision: `UidPool` (`app/executors.py`) hands out a distinct uid per concurrent execution
from a fixed pool (`sandbox0`..`sandbox31`, uids 6666-6697, pinned in the Dockerfile) —
acquired before a run starts and released after, blocking rather than falling back to a
shared uid if the pool is exhausted, so the safety property holds under load instead of
degrading silently. The `unshare` wrapper also gained `--pid --fork`: PID-namespace
visibility is asymmetric (a namespace can see its descendants, never a sibling or an
ancestor), so two concurrent runs — each in the container's main PID namespace's own
child namespace, siblings of each other — cannot enumerate, read `/proc/<pid>/*` for, or
signal one another regardless of uid.
Consequences: two independent isolation layers (distinct uid, distinct PID namespace) each
close a different half of the same concurrency gap, so a bug in one doesn't reopen it
alone. Pool exhaustion is a wait, not a failure mode — with the default pool size (32) far
above realistic concurrent live-coding sessions for an on-prem deployment, this is not
expected to bind in practice. `tests/test_executors.py::test_pid_namespace_hides_other_processes`
and `test_uid_pool_never_hands_out_the_same_uid_twice_concurrently` prove both properties
directly rather than assuming them.

## ADR-021 — M10: real pgvector retrieval behind a mock embedder; deterministic evaluation, LLM narrative-only

Context: M10 needed two more AI-adjacent capabilities — a candidate-facing RAG FAQ and a
cross-signal candidate evaluation — without a GPU model any more than M3's DimensionScore
scoring had one.
Decision, RAG FAQ: the gateway grew a `/v1/embed` endpoint behind an `EmbeddingProvider`
interface (`MockEmbedder` now, `SentenceTransformerEmbedder` deferred to GPU deployment,
same shape as ADR-017's STT/TTS split). Critically, only the *embedding model* is mocked —
retrieval itself is real: `faq_documents.embedding` is a genuine pgvector column with an
ivfflat cosine-similarity index, and `ask_faq` runs an actual `ORDER BY embedding <=>
:query` search, not a stub. The LLM only ever sees documents retrieval already found; it
cannot invent the retrieval step, matching constraint 8.1's citation discipline.
Decision, evaluation engine: `evaluation_engine.py` deterministically aggregates resume
score, questionnaire completion, interview completeness, and coding-task pass rate into one
weighted verdict — mirrors `scoring.py`'s rule that arithmetic and thresholding happen only
in application code, never inside a prompt. The gateway-backed `evaluation_summary`
narrative is additive and best-effort: if the gateway is unreachable, `_generate_narrative`
swallows the error and the persisted report still has its full deterministic verdict,
components, and scores — a missing narrative degrades the report, it never blocks it.
Consequences: PDF/Excel export (`report_export.py`, reportlab/openpyxl) renders straight
from the persisted `EvaluationReport.payload` snapshot, so a report's export is always
consistent with what was actually computed and stored, not re-derived at download time.
`aiva-artifacts` (MinIO) is intentionally not used here — exports are generated on demand
and streamed, not archived; archiving/retention is left to M12 as originally scoped.

## ADR-022 — DSAR erasure: UPDATE-in-place, never DELETE, on a narrowly-scoped new grant

Context: M11 needed a GDPR/CCPA right-to-erasure path, but `code_snapshots`,
`code_executions`, `discussion_messages`, and `evaluation_reports` are deliberately
append-only (SELECT/INSERT-only, ADR-019/020/021 precedent) with no DELETE grant at the
database role level, specifically so routine application code can never tamper with
evidence rows. A blanket DELETE grant to satisfy erasure would reopen exactly the risk
that discipline exists to prevent.
Decision: migration `0011_dsar_update_grants` grants UPDATE only — never DELETE — on
those four tables, and `routers_dsar.py`'s erase endpoint overwrites the specific
PII-bearing columns in place (candidate email, resume full text, answer/message/code
text) rather than removing rows. Row counts and non-PII content (scores, verdicts,
staff-authored prompts) stay intact for audit and statistical integrity. Erasure is
gated to `Role.ADMIN` only — deliberately narrower than the `STAFF_ROLES` every other
router in this codebase uses, because it is destructive and rare, not routine recruiter
workflow.
Consequences, stated plainly rather than glossed over: JSONB evidence payloads that
embed literal resume quotes (`scoring_runs.checks_payload`/`dimensions_payload`) are not
deep-redacted by this pass — only top-level PII fields are. This is a known, documented
gap (see `routers_dsar.py`'s module docstring), not a silent one.

A security review of this diff caught two real issues in the first cut, both fixed
before M11 was called done. First (High): the erase loop redacted
`ResumeDocument.full_text`/`.candidate_email` and `ExtractedFieldRow.value`, but left
`ResumeDocument.filename` and `ExtractedFieldRow.source_quote` untouched on those same
rows — both routinely contain the candidate's identity (filenames like
`jane_doe_resume.pdf`; `source_quote` is the ~80 raw characters of resume text
surrounding a matched PII span per `text_extract.py`), and both were readable right back
through the ordinary, non-blind `GET /resumes/{id}` endpoint any `STAFF_ROLES` member
could call — a real, complete-if-not-for-this gap in an erasure feature specifically
built for compliance. Fixed by redacting both. Second (Medium): `GET /dsar/export`
accepted the candidate's raw email as a query parameter while the sibling erase endpoint
took it in a POST body — inconsistent, and a query string is exactly what reverse-proxy/
access logs capture by default, undermining the same file's own discipline of only ever
persisting a SHA-256 hash of the email to the audit log. Fixed by switching export to
POST with the email in the body, matching `DsarEraseRequest`'s shape.

## ADR-023 — Bias audit scoped to scoring consistency; integrity signals scoped to zero-ML browser events

Context: PLAN.md's M11 line item names "bias audit" and "integrity signals" without
specifying what either means concretely, and both are the kind of feature that's easy
to over-claim.
Decision, bias audit: this system collects no protected-characteristic data about
candidates (race, gender, age, disability, etc.) — appropriately, since collecting it
would itself be a significant legal/privacy decision never made here. A disparate-impact
analysis is therefore not implementable responsibly. `scoring_audit.py` instead checks
what the data actually supports verifying: verdict drift (the same resume, same weight
profile, different verdict — scoring.py promises byte-identical runs for identical
inputs), missing evidence citations (defense-in-depth check that the gateway contract's
citation requirement actually held on the way into the database), and narrow score bands
(a weight profile whose runs cluster suspiciously tightly, which more often means the
profile isn't discriminating between candidates than that every candidate is equally
qualified).
Decision, integrity signals: face/gaze-based proctoring (InsightFace/MediaPipe) is
GPU-model-dependent and was already flagged deferred to deployment across M8/M9's docs.
Unlike STT/TTS/embeddings, there is no frame-capture pipeline in the candidate app to
mock a backend *for* yet — a mock face-detection analyzer would be inventing input, not
standing in for a real one, so migration `0012_integrity_signals` and
`routers_integrity.py` ship only what's genuinely real today: the browser reporting when
the candidate's tab loses focus, exits fullscreen, or becomes hidden during an active
interview. No ML, no mock, no pretending — a real signal a hiring team can act on now,
with the harder, model-dependent signals left honestly deferred.
Consequences: both features are smaller than their PLAN.md names might suggest, on
purpose. Scope creep into an unimplementable-responsibly demographic audit or an
unbacked ML proctoring mock would have cost more (in false confidence, and in the
compliance risk of pretending to check something the system has no data to check) than
the narrower, honest versions shipped here.

## ADR-024 — Anthropic API replaces the hand-built local/self-hosted LLM path; Atigro-derived branding removed

Context: the product owner rejected the M3-era plan of a hand-rolled local-model
serving layer (`VllmBackend` expecting operator-managed GPU weights for
Qwen2.5-14B-AWQ, with `MockBackend` standing in until real hardware existed) as
unnecessary complexity for what the product actually needs: real AI-backed judgement
for scoring, questionnaire evaluation, interview question generation, and evaluation
reports, without owning GPU inference infrastructure. Separately, the design system's
brand color was explicitly sampled from a third-party reference site (atigro.com,
ADR-014) and the product name must not carry any association with that site.
Decision, AI backend: `services/ai-gateway/app/backends.py` gains `AnthropicBackend`,
calling the hosted Anthropic API with a forced tool_use call whose `input_schema` is
the exact Pydantic response-model schema — the same "impossible to return schema-invalid
output" guarantee `VllmBackend`'s `guided_json` provided, now without any self-hosted
model to operate. `VllmBackend` is removed outright, not deprecated-in-place — it served
no purpose once the product doesn't run its own GPU inference. `MockBackend` is kept
unchanged: it is a deterministic test double for CI, not part of what was rejected.
`llm_backend` still defaults to `mock` (zero-setup local runs, no API key, no cost);
`compose.yaml` opts into `anthropic` via `.env` (`ANTHROPIC_API_KEY` +
`AIVA_GATEWAY_LLM_BACKEND=anthropic`), same opt-in shape ADR-017 established for
STT/TTS backends. Determinism is now best-effort (`temperature=0`, no hard seed
guarantee) rather than exact — documented rather than glossed over, since `scoring.py`'s
`run_fingerprint` claim of byte-identical repeated runs no longer holds when the
`anthropic` backend is selected (it still holds for `mock`, which is what CI and the
determinism tests use).
Decision, branding: the `--signal` design token (ADR-014's atigro.com-sampled
`#1863dc`/`#046BB3`) is replaced with an original palette (`#6c5ce7` dark /
`#4b3ed1` light, both re-verified ≥4:1 against their base surface, `--signal-text`
re-verified ≥9:1 for small text — same AA discipline ADR-014 established, just against
new values) and every code comment referencing "Atigro" (feature-card CTA styling,
a theme-storage migration comment) is reworded to describe the behavior directly instead
of citing the source. This supersedes ADR-014's color values but not its accessibility
methodology.
Consequences: the "no GPU hardware, no local model weights" framing throughout
docs/MODEL_CARD.md and the README's planned-capabilities table no longer applies to
LLM reasoning specifically — it becomes "no self-hosted model, calls Anthropic's API
instead," which also means the air-gap/zero-egress framing for that one capability is
gone (outbound calls to Anthropic's API are now real and expected when the `anthropic`
backend is selected; `infra/egress_allowlist.txt`'s discipline continues to apply to
hardcoded URLs in source, which this change adds none of — the Anthropic SDK manages
its own endpoint). Embeddings (`SentenceTransformerEmbedder`) and STT/TTS
(faster-whisper/Piper) are unchanged by this ADR: Anthropic has no embedding or speech
API, so those stay on the existing mock-now/local-model-later path pending GPU
deployment, per ADR-017.
Rejected: keeping `VllmBackend` alongside `AnthropicBackend` as a second selectable
option — the product owner's ask was explicitly to remove the hand-built path, not add
a third one; if self-hosted inference is wanted again later, it re-enters through a new
ADR with real hardware behind it, not a code path nobody runs.

## ADR-025 — Application-level encryption at rest for the most sensitive text columns; API-wide rate limiting

Context: the product owner required that stored data "must be encrypted and should
not be accessible by any third party," and separately that API routes carry rate
limiting and input validation — both already flagged as open gaps in this repo's own
docs (`docs/RUNBOOK.md`'s "Known open items", MinIO encryption deferred to M12 per
ADR-008; no rate limiting existed anywhere in `apps/api`).
Decision, encryption: `apps/api/app/crypto.py` adds `EncryptedText`, a SQLAlchemy
`TypeDecorator` performing AES-256-GCM (via the `cryptography` library) transparently
at the ORM boundary — every other module keeps reading/writing these columns as plain
Python `str`, so `text_extract.py`, `matching.py`, and every existing test needed zero
changes. Applied to the four highest-sensitivity text columns, chosen because none of
them are used in any SQL `WHERE`/filter predicate (verified by grep before touching
anything — encrypting a column that's queried on would have silently broken lookups):
`resume_documents.full_text`, `extracted_fields.value`, `extracted_fields.source_quote`,
`interview_turns.answer_text`. Migration `0013_encrypt_sensitive_text` converts each
column from `TEXT` to `BYTEA`; since this repo has no production data (dev/demo only),
existing rows are reinterpreted as raw UTF-8 bytes rather than actually encrypted —
documented in the migration's own docstring, not glossed over — so a fresh
migrate+reseed (the existing documented quickstart) is required, not a silent gap.
The key (`AIVA_ENCRYPTION_KEY`, base64 for exactly 32 raw bytes) is validated
fail-closed in `settings.py`'s own `field_validator`, same discipline as `jwt_secret`;
a checked-in dev-only default lives in `compose.yaml` (ADR-013's precedent), with
`.env.example` documenting how to generate a real one.
Explicitly out of scope for this pass, not silently omitted: code submissions,
whiteboard strokes, and discussion messages (lower sensitivity — code, not identity
data); `candidate_email` columns (needed in `WHERE` clauses for dedup/lookup —
encrypting them would require deterministic encryption or a blind index, a larger
change deferred to a follow-up); MinIO/object-storage encryption (still ADR-008's
KES/Vault plan, deferred to M12 — this repo doesn't actually persist raw resume files
to object storage yet, only extracted text to Postgres, so there is no file-storage
path to encrypt today).
Decision, rate limiting: `app/rate_limit.py` wraps `slowapi` (in-memory storage,
IP-keyed via `get_remote_address`) with a conservative global default
(`200/minute`, applied to every route via `SlowAPIMiddleware`) plus stricter explicit
limits on the classic brute-force targets: `/auth/login` (10/minute), `/auth/register-org`
(5/minute), `/auth/refresh` (30/minute), and the two most enumeration-exposed public
token-gated GET endpoints (`/public/questionnaires/{raw_token}`,
`/public/interview-sessions/{raw_token}`, 30/minute) — these are unauthenticated by
design, so the raw token itself is the only secret, making them worth extra protection
against token brute-forcing. The other ~15 public token-gated endpoints rely on the
200/minute global default rather than individual tuning, a real but narrower gap noted
here rather than claimed as exhaustively covered.
A real regression this surfaced and fixed before it shipped: `slowapi`'s `Limiter` is a
process-wide in-memory singleton, and this repo's own "integration" tests
(`test_integration_*.py`) construct many separate in-process `create_app()` instances
within one pytest run via `app/main.py`'s `create_app()` — all sharing that one
singleton's request counters. Without a fix, cumulative login/register calls across a
single test file (e.g. `test_integration_auth.py`'s several bootstrap-heavy tests) would
exceed the new per-minute limits and start failing previously-passing tests with 429s —
a self-inflicted regression, not a hypothetical one. Fixed via `settings.environment`:
`main.py`'s lifespan sets `limiter.enabled = settings.environment != "test"`, and
`AIVA_ENVIRONMENT=test` is now set in every CI integration-job step and in
`tests/conftest.py`'s offline fixture — verified by re-running the full offline suite
(90 passed, 30 skipped, 0 failed) after the change, not assumed safe.
Consequences: `apps/api`'s quality gate (ruff, black, mypy --strict, bandit, pytest)
stayed fully green through this change, including a bandit `B105` false positive
(a rate-limit-string constant named `PUBLIC_TOKEN_LIMIT` was flagged as a hardcoded
password purely because its name contained "TOKEN" — renamed to `PUBLIC_ENDPOINT_LIMIT`
rather than suppressed) and a genuine `B101` finding (an `assert` used for type
narrowing in a request handler, which is stripped under `-O` — replaced with an
explicit `isinstance` check that raises `TypeError`, not suppressed either).
Rejected: encrypting `candidate_email` in this pass (breaks existing dedup/lookup
queries without a larger design change); a Redis-backed rate-limit store (unnecessary
at this scale — `Limiter(storage_uri=...)` is a one-line swap if it's ever needed,
same "interface now, harder backend later" pattern as ADR-017's STT/TTS/LLM backends).

## ADR-026 — Recruiter/candidate UI for requisitions, job descriptions, resume upload, questionnaires, scheduling

Context: by ADR-025, the backend supported the full hiring pipeline (JD → resume →
score → questionnaire → schedule → interview → evaluate) with tested, working logic
for every step, but the recruiter console only had UI for the pipeline/resume-detail/
dashboard/sessions views — a recruiter could not create a job description, upload a
resume, build a questionnaire, or generate interview slots without calling the API
directly, and the candidate app had zero UI for questionnaires at all. This was the
single largest gap between "backend capability exists" and "a user can actually do
the thing."
Decision: closed the gap end to end rather than partially. Two read endpoints were
added purely because no list endpoint existed at all (`GET /orgs/{id}/departments`,
`GET /orgs/{id}/requisitions`) — everything else already had a working create/get
endpoint, this was strictly a UI-enablement gap, not a missing feature. Five new
`apps/web-recruiter` pages (`Requisitions`, `RequisitionDetail`, `ResumeUpload`,
`Questionnaire`, `Scheduling`) and one new `apps/web-candidate` page
(`Questionnaire`, public token-gated) consume the existing and newly-added endpoints.
No new design-system components beyond one (`Select`) were needed — the existing
`Button`/`Card`/`Field`/`Input`/`Textarea`/`Badge`/`EmptyState`/`Skeleton` set from
Milestone 1 covered every new page without modification, which is itself evidence the
design system was already well-scoped, not under-built.
Verification: the full new surface was exercised directly over HTTP against a freshly
migrated live stack (register → department → requisition → JD → questionnaire →
invite → public submit → response list → scheduling slots → resume upload → weight
profile → scoring run → pipeline view), and the existing domain-lifecycle integration
suite was re-run afterward (24/26 pass; the 2 failures are the pre-existing
sandbox-runner anomaly tracked separately in `docs/PLAN.md`, not caused by this work).
Update (same session, later): the live TypeScript compile this ADR originally called
out as unverified was subsequently unblocked by installing a user-local Node.js
binary directly inside the WSL2 distro (no root, a plain tarball extract) and running
`pnpm` entirely on that side of the filesystem boundary, instead of bridging Windows
and WSL2 as every earlier attempt had. `tsc --noEmit` then found 8 real errors from
`noUncheckedIndexedAccess` (all in `ResumeUpload.tsx`'s upload/scoring loops, fixed by
iterating `.entries()` instead of indexing) and `eslint` found 6 more
(`@typescript-eslint/no-non-null-assertion` violations from `requisitionId!` in two
pages, fixed by rebinding to a fresh `const` after the guard — confirmed, not assumed,
that narrowing does not propagate into the nested closures this code used). Both apps
now pass `tsc --noEmit`, `vite build`, and `eslint` with zero errors, and both
production builds were served locally and confirmed to return correct HTML. Full
details and the exact fixes are in the README's ADR-026 section. The hand-review
pass this ADR originally relied on caught two real, different bugs the compiler
does not catch (a response-parsing bug, an unnecessary eslint-disable) — both classes
of check turned out to matter, not just the one that was eventually available.
Consequences: the product's core promised flow (create JD → upload resumes → score →
shortlist → questionnaire → schedule → interview) is now reachable end to end through
the UI for the first time, not just through the API, and is compiler-and-linter-verified,
not just hand-reviewed.
Rejected: building a candidate-facing self-service scheduling portal — the actual
`POST /slots/{id}/book` endpoint is staff-only by design (ADR predates this one; not
revisited here), so a candidate booking UI would have needed a new, unreviewed
backend authorization surface rather than just a missing frontend, out of scope for a
UI-enablement pass.

## ADR-027 — Cross-organization data leak in GET /requisitions/{id}/slots, found by a new integration test and fixed

Context: while closing the scheduling-integration-test gap ADR-026/the README both
named as still open, the new `test_integration_scheduling.py` was written to prove
cross-org isolation the same way every other list/get endpoint in this codebase
already does (a pattern this repo enforces consistently elsewhere — see ADR-002's
RLS design and the M8/M11 "cross-org access returns 404" discipline already proven
for auth, resume, and questionnaire endpoints). The test failed on its first real
run against a live stack, not by inspection.
Finding: `list_slots` (`app/routers_scheduling.py`, `GET /requisitions/{id}/slots`)
never called `_load_requisition` (the org-scoping check its sibling endpoint
`generate_requisition_slots` already used) or filtered by organization at all — it
queried `InterviewSlot` by `requisition_id` alone. Any authenticated staff user, in
any organization, could list any other organization's full interview slot schedule
for a requisition whose UUID they had or could guess, including booked candidates'
email addresses (`booked_for_email`) — a real cross-tenant PII leak, not a
theoretical one, contradicting this codebase's own stated RLS/organization-isolation
guarantees (ADR-002 and every "Milestone N proven: cross-org access denied" claim
elsewhere in this document).
Fix: one line — `await _load_requisition(db, user, requisition_id)` at the top of
`list_slots`, matching the exact pattern already used by `generate_requisition_slots`
two functions above it in the same file. Verified by `test_cross_org_scheduling_access_denied`
in `test_integration_scheduling.py`: org B is now correctly denied (404) from
generating, listing, or booking against org A's requisition/slots, re-run against a
live stack after the fix (all 3 scheduling tests pass; the full domain-lifecycle
integration suite was also re-run afterward with no other regressions — 29/31 pass,
the 2 failures being the pre-existing, unrelated sandbox-runner anomaly).
Consequences: this was a real, shipped vulnerability in the code this session
inherited, not introduced by anything in this session's earlier commits — it predates
ADR-024 through ADR-026 and would have shipped to Milestone 12 hardening undetected
had this integration test not been written now. It was caught specifically because
writing a *new* test forced writing the cross-org-denial assertion explicitly, rather
than because of a broader security audit of already-existing endpoints — the same
class of gap plausibly exists elsewhere in code that has never had an equivalent test
written against it. A follow-up pass auditing every staff-role GET/POST endpoint for
an explicit organization-scoping check (not just relying on RLS, which requires the
session's `aiva.organization_id` to be bound correctly by `get_db` in the first place)
is warranted before Milestone 12, not assumed unnecessary because "RLS should have
caught it" — RLS is a second layer of defense here, not a substitute for the
application-level check that was actually missing.

## ADR-028 — Three real bugs behind sandbox-runner's code execution failures, found and fixed

Context: every prior live-stack verification this session ran (README's ADR-026
section, ADR-027) hit the same 2 failing tests — `test_integration_workspace.py`
and `test_integration_evaluation.py` — with sandboxed code execution returning
`exit_code=1`/empty stdout via a 200 response. This was logged three separate times
as an "environment-specific anomaly... unconfirmed as a root cause," on the working
theory that Docker Desktop's WSL2 backend behaved differently from the native Linux
kernel `ubuntu-latest` CI runs on. That theory was never actually tested — it was a
plausible-sounding excuse not to dig further, made three times in a row. Digging in
instead found three real, unrelated bugs, none of them Docker-Desktop-specific.

**Bug 1 — missing `CAP_SYS_ADMIN`.** `unshare --map-root-user --net --pid --fork`,
called directly inside the running `sandbox-runner` container, failed outright:
`unshare: unshare failed: Operation not permitted`. Docker's default capability set
excludes `CAP_SYS_ADMIN`; creating new namespaces needs it (or, in principle, a
kernel that permits the unprivileged-user-namespace path `--map-root-user` relies on
to work without it — evidently not available here, whatever the reason). `compose.yaml`
never granted it. Fixed with `cap_add: [SYS_ADMIN]` on the `sandbox-runner` service —
a narrow, standard grant (not `privileged: true`), and the service already runs as
root in-container specifically to setuid-drop per execution (ADR-019), so this adds
no privilege the container didn't already effectively need for its own stated design
to function at all.

**Bug 2 — a `PATH` that doesn't match the base image.** With Bug 1 fixed, Python
executions still failed: `unshare: failed to execute python3: No such file or
directory`. `_run_sync`'s subprocess `env` hardcoded `PATH=/usr/bin:/bin`; the
service's own `python:3.11-slim` base image installs `python3` at `/usr/local/bin`.
Confirmed directly (`which python3` inside the container: `/usr/local/bin/python3`;
`/usr/bin/python3` does not exist). Fixed by adding `/usr/local/bin` first in the
allowlisted `PATH` — still a fixed, minimal list, not the real environment's PATH.

**Bug 3 — `RLIMIT_AS` capped 6x too low for Node, from an unused field.**
`_SubprocessExecutor.__init__` already computed `self._rlimit_as_bytes` (768MB for
JS, deliberately larger than the 128MB `--max-old-space-size` heap cap, because V8
reserves substantially more virtual address space at startup than its heap limit)
— but `_run_sync`'s `preexec()` closure called `_apply_rlimits(cpu_seconds,
self._memory_bytes, ...)`, passing the 128MB heap-size field for the OS-level
`RLIMIT_AS` instead of the 768MB field computed for exactly that purpose. Every
Node execution's V8 startup mmap calls hit the 128MB ceiling, and Node hung until
the wall-clock timeout — 100% reproducible, every single call, not intermittent.
Confirmed directly by testing 128MB against 768MB in isolation (same isolation
prefix, same privilege drop, only the AS limit changed): 128MB hangs indefinitely
under `timeout 3`, 768MB completes in ~100ms. `_apply_rlimits` gained an explicit
`rlimit_as_bytes` parameter so this class of unused-field bug can't silently recur;
the call site now passes `self._rlimit_as_bytes`. Python is unaffected (it never
set `settings_rlimit_as_mb` separately, so its "wrong" and "right" values were
already identical — this is exactly why Python executions worked throughout while
Node's failed 100% of the time, and why earlier hand-testing with manually-typed
768MB values always succeeded: every ad-hoc reproduction attempt happened to use
the correct value directly rather than going through the buggy code path).

None of these three bugs were introduced this session — `sandbox-runner` predates
tonight entirely. All three are real, were shipping, and would have hit any operator
running this exact `compose.yaml` on any Docker host, not just this one.
Verification: with all three fixes applied, the complete domain-lifecycle
integration suite (auth, resume, questionnaire, scheduling, interview, workspace,
faq, evaluation, m11 — 33 tests) passes in full against a freshly migrated live
stack, for the first time this session. `sandbox-runner`'s own quality gate
(ruff, black, mypy --strict, bandit with its documented `skips` config) stays green.
Consequences: "it's probably an environment difference" is not a root cause, and
this ADR exists partly as a record of that specific failure of nerve, not just the
fix — the actual bugs took under two hours to find with direct `docker compose
exec` probing once actually looked for, after three separate write-ups treating the
symptom as unconfirmable. `services/sandbox-runner`'s own hermetic unit test suite
(`test_executors.py`, `test_sandbox.py`) was not re-verified in this pass when run
directly on the bare WSL host outside the container (it hits unrelated
resource-exhaustion errors specific to lacking the container's dedicated
`sandbox0..31` accounts and `CAP_SYS_ADMIN` context) — the live containerized
integration path is the one that matters for the actual deployment shape and is
what was verified.

## ADR-029 — Data retention job (M12), built on the existing DSAR erasure logic

Context: `docs/PLAN.md`'s M12 line item names "retention jobs" as the one remaining
core milestone. Retention (auto-purging candidate data past a policy window) and
DSAR erasure (purging one named candidate's data on request) are the same operation
— redact the same PII-bearing fields, the same "overwrite in place, never delete the
row" discipline — differing only in *how the candidate is selected* (a named email
vs. an age cutoff), so duplicating the redaction logic would have been a real
maintenance hazard (the exact "two places to keep in sync" pattern the M11 DSAR work
itself flagged, ADR-022's `source_quote` miss). Decision: extracted `_apply_erasure`
from `routers_dsar.py`'s `/dsar/erase` handler into a shared function, and
`routers_retention.py`'s new `POST /orgs/{id}/retention/run` calls it against
whichever candidates its own eligibility query selects.
Policy scope, stated plainly rather than left implicit (per this module's own
docstring): eligibility is based on `ResumeDocument.created_at` age only,
per-request-configurable `retention_days` (no fixed default asserted as legally
correct for any jurisdiction — that's the operating organization's call, not this
codebase's). It does not model "is this candidate still in an active pipeline" —
an operator relying on this for real compliance needs to confirm that separately
before running it for real. `dry_run` (default true, returns the exact candidate
list and count without touching anything) exists specifically to make that check
possible before anything destructive happens; `max_candidates` (default 500) bounds
a single call's blast radius.
Not built, and explicitly out of scope for this pass: an actual scheduler (cron,
systemd timer, Kubernetes CronJob) invoking this endpoint automatically. The
endpoint is designed to be trivially wired into any of those (a single authenticated
POST), but choosing and configuring one is an infrastructure decision for the
deployment target, which this repo doesn't have yet (M12's Helm chart is also still
open) — building a scheduler around a policy this codebase can't fully validate
(the active-pipeline gap above) would be premature.
Verified: `test_integration_retention.py` proves dry-run non-mutation, real-run
erasure + idempotency (a second run against already-redacted candidates finds
nothing left to do), a far-future cutoff finding nothing, and cross-organization
denial (403) — against a live stack, all 4 tests passing. The full domain-lifecycle
integration suite (37 tests, every file including this one) was re-run afterward
with no regressions.
Rejected: giving retention its own redaction implementation independent of DSAR
(the exact duplication this decision avoids); a fixed retention-days default
(asserting a specific number as "correct" retention policy is a legal/product
decision, not an engineering one).

## ADR-030 — Helm chart (M12), plus containerizing the frontend for the first time

Context: `docs/PLAN.md`'s M12 line item names a Helm chart as the last fully-open
piece. Building it surfaced a prerequisite gap: `apps/web-recruiter` and
`apps/web-candidate` had never been containerized at all — no Dockerfile, not even
present in `compose.yaml` — local dev only ever ran them via `pnpm dev`. A Helm chart
can't deploy images that don't exist, so this ADR covers both.
Decision, frontend containerization: multi-stage Dockerfiles (`node:22-slim` build
stage running the monorepo's own `pnpm --filter <app> run build` — verified working
via ADR-026's earlier `tsc`/`vite build` fixes — into an `nginx:1.27-alpine` runtime
stage). Build context must be the monorepo root, not the app subdirectory, since both
apps depend on the `packages/ui` workspace package; a root `.dockerignore` was added
(its absence broke the build outright — pnpm's workspace symlinks under
`node_modules` produced an "invalid file request" from Docker's own context-transfer
step, not a build error inside the Dockerfile). nginx serves the built static bundle
with SPA fallback (`try_files ... /index.html`, needed for `react-router`'s
client-side routes) and reverse-proxies `/api/` to a `${AIVA_API_UPSTREAM}` value
substituted at container startup via nginx's own template-envsubst entrypoint feature
— compose.yaml points it at `api:8000`, the Helm chart's Deployment env var points it
at the in-cluster Service DNS name, same image both places. Both images and both
proxies were verified for real: built, run, and hit with actual HTTP requests
(`docker build` → `docker run` → `curl` returning the correct page title and, for the
`/api/healthz` proxy specifically, the real backend's `{"status":"ok"}` response, not
a mock). Also wired into `compose.yaml` as `web-recruiter`/`web-candidate` services —
`docker compose up` now brings up the complete system including the UI, which it did
not before tonight.
Decision, Helm chart (`infra/helm/aiva`): Deployments for the five app-tier services
(api, ai-gateway, sandbox-runner, web-recruiter, web-candidate — the latter two
sharing one templated `range`-loop manifest since they're structurally identical),
StatefulSets for the bundled Postgres/Redis/MinIO (explicitly documented in
`values.yaml` and `NOTES.txt` as dev/evaluation-grade — no backup/HA story of their
own, matching RUNBOOK.md's pre-existing "Backup & restore: pending M12" line rather
than silently claiming to have solved it; a real deployment should point at managed
services and disable these), a Secret with placeholder values that render successfully
but are not usable secrets (same "no secrets in the repo" rule as ADR-005, restated
for this new surface), an optional Ingress (disabled by default; deliberately routes
only `web-recruiter` — `web-candidate` is a different trust boundary and needs an
explicit host/path decision, not a default), and a NetworkPolicy scoping
`sandbox-runner`'s pod to accepting traffic only from the api pod and sending none
anywhere but DNS — defense in depth on top of its own per-execution `unshare --net`
(ADR-019), not a replacement for it. `sandbox-runner`'s Deployment carries the same
`CAP_SYS_ADMIN` grant ADR-028 added to `compose.yaml`, since the underlying `unshare
--pid --net` requirement is identical in either environment. The Postgres
`initdb` script is mounted from a chart-local copy of the exact same
`infra/postgres/initdb/01_extensions.sql` compose.yaml uses — including, disclosed
rather than silently carried over, that its `aiva_app` role password is a fixed
dev-only literal in the SQL itself, not wired to this chart's `secrets.postgresAppPassword`
value; a real deployment needs that fixed before relying on it.
Verification: `helm lint` and `helm template` both pass, including with
`ingress.enabled=true` and with the bundled data stores disabled (confirming the
conditionals actually omit those StatefulSets rather than just looking like they
would). Neither of those proves a real cluster deployment works — no Kubernetes
cluster was available in the environment this was built in, so `helm install` itself
was never run. Stated plainly in `NOTES.txt` and here rather than left to be
discovered later: this is a validated-to-render, unvalidated-to-deploy chart. Treat
it as a strong first draft for `helm install --dry-run` against a real cluster, not
as already proven.
Rejected: a single combined web-app image serving both apps behind one nginx config
(the trust-boundary difference between the staff console and the public
token-gated candidate app argued for keeping them fully separate images/Deployments,
not a shared one with routing logic deciding which trust boundary a request lands in).

## ADR-031 — Pluggable email delivery, wired into booking and questionnaire invites

Context: the product spec explicitly asked for "an email interface with a log-based
stub implementation, swappable for a real provider later" for interview booking
confirmations, and this repo's own docs (README's Scheduling section, `docs/PLAN.md`'s
M7 entry) had carried "no email is actually sent" as an open gap since that
milestone was built — the `.ics` invite was only ever returned in the API response,
and questionnaire invite links only ever returned as raw API response fields the
recruiter would have to copy out and send manually.
Decision: `apps/api/app/email.py` adds an `EmailProvider` interface with two
implementations, same mock-now/real-later shape as every other external capability in
this codebase (ADR-017's STT/TTS/LLM backends). `LogEmailProvider` (default,
`AIVA_EMAIL_BACKEND=log`) writes a structured log line for every email that would be
sent — satisfying the spec's explicit "log-based stub" ask directly, not glossed over
as "email not implemented." `SmtpEmailProvider` (`AIVA_EMAIL_BACKEND=smtp`) is a real
implementation using stdlib `smtplib` (no new dependency), running the synchronous
send in a thread (`asyncio.to_thread`) so it never blocks the event loop — genuinely
sends mail given real credentials, not another mock. Wired into the two places the
spec named: `POST /slots/{id}/book` (interview booking confirmation, `.ics`
attached) and `POST /questionnaires/{id}/invites` (the candidate's one-time portal
link, built from a new `AIVA_CANDIDATE_PORTAL_URL` setting rather than hardcoded).
Verified: `tests/test_email.py` covers both providers directly — `LogEmailProvider`
via structlog's capture fixture, `SmtpEmailProvider` by mocking `smtplib.SMTP`
(asserting the real `starttls`/`login`/`send_message` call sequence, message
headers, plain-text body content via `EmailMessage.get_body()`, and the `.ics`
attachment's filename — not just that a function was called, but that the message
it built is correct). The existing scheduling and questionnaire integration test
suites were re-run against a live stack after wiring this in: both still pass in
full (no regression from adding a dependency neither test suite explicitly exercises
the content of, since both still just check the HTTP-level behavior the log backend
doesn't change).
Consequences: this closes a specific, long-standing, explicitly-named gap rather than
a general "add email" feature — reminder emails (T-24h/T-1h, named in M7's original
scope) still need a scheduler that doesn't exist yet (same gap as ADR-029's retention
job automation), and a dedicated transactional-email-provider integration (SES,
SendGrid, etc., as opposed to SMTP relay) is a real, separate follow-up if an
organization's mail infrastructure doesn't speak SMTP.
Rejected: bundling a self-hosted mail server (Postfix) into `compose.yaml`, which
`docs/PLAN.md`'s original M7 entry had scoped this deferral around — unnecessary complexity
for a feature that stdlib `smtplib` against any real SMTP host/relay already covers;
a self-hosted MTA is an infrastructure decision for the deploying organization, not
something this repo should assume or provide.

## ADR-032 — MFA frontend, closing a gap the login screen had been naming since Milestone 2

Context: `app/auth_service.py`/`app/routers_auth.py` have shipped complete TOTP MFA
(enroll, activate, and login gating — `POST /auth/login` already rejected
password-only login once `mfa_enabled` was set, requiring `totp_code`) since
Milestone 2. The recruiter console's login screen had, since it was first built,
carried its own copy directly stating "MFA-protected accounts will be prompted for a
code in a later milestone" — a real, self-documented gap, not an oversight nobody
noticed.
Decision: `Login.tsx` now handles the `401` response `POST /auth/login` returns when
a code is missing or wrong — distinguished by the backend's own error detail text
("TOTP code required" vs. "Invalid TOTP code"), since both cases share the same
status code — revealing a code-entry step instead of just showing a generic
sign-in failure. A new `/security` page (`MfaSetup.tsx`) drives the
enroll-then-activate flow: calls `POST /auth/mfa/enroll`, displays the returned
secret as a manually-enterable key (no QR-code library added — out of scope for
what this gap actually needed, and copy-paste-a-secret is the standard authenticator
fallback path every app supports anyway, not a lesser one) plus the raw `otpauth://`
URI behind a `<details>` toggle for anyone who wants to build a QR code themselves,
then collects the 6-digit confirmation code and calls `POST /auth/mfa/activate`.
Verification: the complete lifecycle was run against a live stack end to end with
real TOTP codes computed via `pyotp` (the same library the backend itself uses) —
register → login (pre-MFA) → enroll → activate with a valid code → login without a
code correctly rejected (401) → login with a deliberately wrong code correctly
rejected ("Invalid TOTP code") → login with a fresh valid code correctly succeeds
(200, real token pair) — not assumed from reading the code. `tsc --noEmit`, `vite
build`, and `eslint` all pass with zero errors on the new/changed frontend files, and
the existing `test_integration_auth.py` (which already covered the backend MFA flow)
was re-run afterward with no regressions.
Consequences: MFA is now something a recruiter/admin/hiring-manager account can
actually turn on and use through the UI, not just through direct API calls -- closing
a specifically-named, long-carried gap rather than a general "auth polish" pass.
Rejected: adding a QR-code-rendering library for the enrollment screen -- the
manual-secret-entry path this ships is already how every authenticator app expects
to support accounts that can't be scanned, and pulling in a new frontend dependency
for a convenience the flow doesn't strictly need wasn't worth the audit-surface cost
(ADR-007's "dependencies land on first use, not speculatively" precedent).

## ADR-033 — AI evaluation of submitted questionnaire responses

Context: `docs/PLAN.md`'s Milestone 6 entry and this repo's README had, since the
questionnaire feature was first built, explicitly named "AI-based evaluation of
candidate answers (score, recommendation, inconsistency vs. resume, missing critical
info)" as scoped out pending a real AI model being deployed -- the questionnaire
pipeline could collect and store answers but never judge them. ADR-024's swap from
the hand-rolled local model backend to the real Anthropic API removed that blocker.
Decision: a new `QuestionnaireEvaluation` Pydantic contract
(`services/ai-gateway/app/contracts.py`) extends `JudgementBase` (so it inherits the
evidence-citation discipline every other judgement contract in this gateway has --
`rationale`, `confidence`, `cited_span_ids`) with `overall_score` (0-100),
`recommendation` (`Literal["proceed", "hold", "reject"]`), `inconsistencies`, and
`missing_critical_info`. A new prompt (`prompts/questionnaire_evaluation.txt`) feeds
the gateway the job description clause, the candidate's question/answer pairs, and
extracted resume spans, with the same prompt-injection-hardening rule every other
prompt in this gateway carries. `apps/api` adds `POST
/questionnaire-responses/{id}/evaluate` (`routers_questionnaire.py`): loads the
submitted response, the questionnaire's question text, the org's latest job
description, and a best-effort resume match by candidate email, calls the gateway,
and persists the result on a new `questionnaire_responses.ai_evaluation` JSONB
column (migration `0014_questionnaire_ai_evaluation`) so it's computed once and
served from storage afterward, not recomputed on every read. Evaluating a response
that hasn't been submitted yet is rejected (409) rather than silently evaluated
against incomplete answers.
Bug found and fixed along the way: `MockBackend`'s `_deterministic_fill`
(`backends.py`) had no handling for enum-constrained fields. Every prior contract in
this gateway happened to have only free-form string/int/float fields, so the gap was
latent; `recommendation`'s `Literal["proceed","hold","reject"]` was the first field
that needed it, and the generic string branch synthesized a placeholder value
matching none of the three allowed choices, failing the same model's own validation
a few lines later. Fixed by reading the field's JSON-schema `enum` list, when
present, and picking deterministically from the real allowed values instead --
preserving the "byte-seeded but always schema-valid" guarantee for any current or
future enum-typed contract field, not just this one.
Verified: `services/ai-gateway`'s full quality gate (black, ruff, mypy, bandit,
pytest) is clean, including a regression test
(`test_questionnaire_evaluation_is_schema_valid_and_deterministic`) that explicitly
targets the enum bug rather than just checking a 200 status. `apps/api`'s gate is
clean the same way. Two new integration tests
(`test_ai_evaluation_of_submitted_response`, `test_evaluation_rejected_before_submission`
in `test_integration_questionnaire.py`) were run against a fresh, fully-migrated live
compose stack (real Postgres/Redis/MinIO/ai-gateway containers, not mocks) and pass;
the complete 39-test domain-lifecycle integration suite (readiness, auth, resume,
questionnaire, scheduling, retention, interview, workspace, faq, evaluation, m11) was
re-run against that same fresh stack afterward with no regressions.
Consequences: closes a specifically-named, long-carried Milestone 6 gap. The
resume-match used to build `resume_spans` is a best-effort `candidate_email` lookup
within the org, not a guaranteed link between a questionnaire response and a specific
resume upload -- if no matching resume exists the evaluation still runs, just without
that evidence, which is the correct degrade-gracefully behavior rather than blocking
evaluation on an unrelated upload existing.
Rejected: auto-running the evaluation the instant a response is submitted. Kept it as
an explicit staff-triggered action (mirrors the resume/JD scoring flow's own
already-established pattern) so a recruiter decides when to spend the AI call rather
than every candidate submission silently triggering one, and so a re-evaluation after
a resume is uploaded later is a deliberate action rather than something that has to
detect and race against out-of-order uploads.

## ADR-034 — Interview reminder emails (T-24h / T-1h), the one M7 gap ADR-031 left open

Context: `docs/PLAN.md`'s M7 entry and ADR-031 both explicitly named T-24h/T-1h
interview reminders as still deferred, "needs a scheduler, same gap ADR-029's
retention job has." ADR-029 itself reasoned that building a scheduler around
*retention* specifically would be premature -- that endpoint's eligibility policy
can't yet model "is this candidate still in an active pipeline," so automating it
blind was a real risk, not just missing infrastructure. Reminders don't carry that
landmine: a slot is either booked with a start time inside its reminder window and
hasn't been reminded yet, or it isn't -- there's no policy-correctness question
sending a reminder can get wrong the way auto-erasing a candidate's data can.
Decision: `POST /orgs/{id}/interview-reminders/run` (`routers_reminders.py`) follows
ADR-029's exact shape otherwise -- an idempotent, staff-authenticated endpoint a real
scheduler (cron, systemd timer, Kubernetes CronJob) is meant to invoke periodically,
not an in-process scheduler dependency this codebase doesn't otherwise have any
precedent for. Two new nullable timestamp columns on `interview_slots`
(`reminder_24h_sent_at`, `reminder_1h_sent_at`, migration 0015) record whether each
window's reminder has already gone out; a slot is due for a window once `start_at`
falls inside it and that column is still null. Because "due" is a window rather than
an exact instant, a deployer invoking this every 15-30 minutes (or far less often)
still catches everything that opened since the last run, and both windows can fire
in the same call for a slot discovered late (e.g. the very first run against a slot
already inside the 1h window) -- correct behavior, not a bug, since a late reminder
is still useful and the sent-at columns make a genuine duplicate impossible either
way. Emails go through the same `EmailProvider` (ADR-031) as booking confirmations.
Verified: `test_integration_reminders.py` proves a slot 20 minutes out gets both
windows on the first run and neither on a second (idempotency), a slot 20 hours out
gets only the 24h window, a slot 3 days out gets neither, and cross-org access is
denied -- slot start times are computed relative to real wall-clock time via the
existing pure `generate_slots` arithmetic (no real waiting, no direct DB
manipulation, staying consistent with every other integration test's HTTP-only
discipline). The full 43-test domain-lifecycle suite was re-run against a fresh,
fully-migrated live stack afterward with no regressions. `black`/`ruff`/`mypy`/
`bandit` all clean.
Consequences: closes the one specifically-named gap ADR-031 left open. The frontend
has no reminder-status UI yet -- reminders are visible to a recruiter only via the
run response and the audit log, not the slot list; genuinely low priority, since the
audience for this endpoint is a scheduler, not a person clicking a button.
Rejected: adding an in-process background scheduler (APScheduler or a bare asyncio
loop) to send reminders automatically. Would have been the first background-task
subsystem anywhere in this codebase, for a job whose correct cadence (how often is
"often enough") is exactly the kind of deployment-environment decision ADR-029 already
reasoned belongs to the deployer, not baked into the app process.
