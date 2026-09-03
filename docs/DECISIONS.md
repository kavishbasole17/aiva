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
