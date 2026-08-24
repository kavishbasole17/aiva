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

## Remaining milestones

| # | Milestone | Depends on |
|---|---|---|
| M3 | ai-gateway + local models + constrained decoding + eval harness scaffold | GPU hosts, model weights in image |
| M4 | Resume ingest/spans, JD processing, matching, scoring, shortlisting | M2, M3 |
| M5 | Recruiter console: pipeline board, candidate detail, Evidence Spine v1 | M1, M4 |
| M6 | Questionnaire builder + candidate portal + evaluation | M4 |
| M7 | Scheduling, availability rules, .ics, SMTP reminders | M6 |
| M8 | LiveKit pre-check, consent, STT/TTS adaptive interview loop, HUD | M7 |
| M9 | Sandbox runner, editor, whiteboard, screen share, task discussion | M8 |
| M10 | RAG FAQ, evaluation engine, report + PDF/Excel export | M9 |
| M11 | Dashboard + blind screening, bias audit, integrity signals, kits, DSAR | M10 |
| M12 | Load test, pen-test pass, retention jobs, Helm chart | M11 |

## Known open items carried forward

- Local Docker Engine install in WSL pending operator action; compose stack is
  proven via CI integration job meanwhile.
- Coverage thresholds and golden-set content begin at M4 when scoring logic exists.
- MinIO server-side encryption wires into KES/Vault at production hardening (ADR-008).

