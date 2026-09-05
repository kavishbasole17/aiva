# RUNBOOK

Living document. Sections marked **(pending Mx)** are declared gaps, not omissions.

## Development quickstart

```bash
docker compose up -d
scripts/wait_ready.sh
docker compose exec api alembic upgrade head
scripts/seed_demo_account.sh
```

`readyz` returns 200 only when Postgres, Redis, and MinIO (including the
`aiva-artifacts` bucket) are reachable; `wait_ready.sh` polls it until green —
it does **not** mean the schema exists yet. A fresh `postgres_data` volume
starts empty; `alembic upgrade head` must run once against it before any
endpoint that touches the database will work (otherwise every DB-backed
request 500s with `UndefinedTableError`). It's idempotent — safe to re-run
after every `docker compose down --volumes` reset, and CI does the equivalent
via `.github/workflows/ci.yml`'s `integration` job.

Note: `docker compose up --wait` is deliberately not used — the one-shot
`minio-init` bucket creator exits 0 on success and `--wait` reports that as a
failure (see DECISIONS ADR-013).

## Test credentials

`scripts/seed_demo_account.sh` calls `POST /auth/register-org` against the
dev API to create a fixed demo organization + admin/recruiter account. It is
idempotent — safe to re-run; a 409 (already exists) is treated as success.
The same fixed credentials are reused every time so they stay usable across
resets of the dev database:

| Field | Value |
|---|---|
| Web app | `web-recruiter`, http://localhost:15173 |
| Organization | `AIVA Demo Org` |
| Email | `demo.recruiter@aiva.test` |
| Password | `AivaDemo#2026!` |

These are dev-only, never used outside `docker compose` locally, and are not
secrets — override via `AIVA_DEMO_ORG` / `AIVA_DEMO_EMAIL` /
`AIVA_DEMO_PASSWORD` env vars if you need a different seed. `apps/web-candidate`
has no login (token-gated only); a per-interview join link/token is generated
through the recruiter console instead.

## Services (dev)

| Service | Host port | Notes |
|---|---|---|
| API | 18000 | FastAPI, `/openapi.json` exposed, docs UI disabled |
| Postgres 16 | 15432 | user `aiva`, db `aiva`, pgvector + pg_trgm enabled |
| Redis 7 | 16379 | AOF on |
| MinIO | 19000 (console 19001) | bucket `aiva-artifacts` |
| ai-gateway | 19100 | mock LLM/STT/TTS backends; `/media-backends` shows active providers |
| sandbox-runner | 19200 | live-coding execution; `/runtimes` shows supported languages |
| web-recruiter dev | 15173 | `pnpm dev` in `apps/web-recruiter` |
| web-candidate dev | 15174 | `pnpm dev` in `apps/web-candidate` |

## Configuration

All runtime config arrives via `AIVA_*` environment variables, validated at startup;
missing or malformed values fail boot. See `.env.example`. Compose carries dev-only
values inline (ADR-005). Production secrets come from the org's Vault/KMS via Helm
(pending M12).

## Air-gap / egress policy

```bash
scripts/check_no_egress.sh
```

Fails on any scheme-bearing URL outside `infra/egress_allowlist.txt`. Allowlist rules
are `path-glob::line-regex` pairs and must only ever reference loopback/internal
hosts. To verify enforcement works, plant a violation and re-run — CI does this
implicitly by failing builds; local negative test:

```bash
printf 'const x = "https://example.invalid";\n' > apps/web-recruiter/src/_probe.ts
scripts/check_no_egress.sh   # expect exit 1
rm apps/web-recruiter/src/_probe.ts
```

## Quality gates

```bash
pnpm -r lint && pnpm -r typecheck && pnpm -r build
ruff check apps/api && black --check apps/api
mypy --strict apps/api/app
bandit -c pyproject.toml -r apps/api/app
pytest apps/api/tests            # unit; integration needs AIVA_INTEGRATION=1 + live stack
```

## Load testing

```bash
AIVA_ENVIRONMENT=test docker compose up -d --build   # disables rate limiting (ADR-025);
                                                       # see scripts/load_test.py's docstring
                                                       # for why that matters for this measurement
scripts/wait_ready.sh
python3 -m alembic -c apps/api/alembic.ini upgrade head   # or the usual apps/api migrate step
python3 scripts/load_test.py --base-url http://localhost:18000 --concurrency 20 --requests 300
```

Stdlib-only (`urllib` + `concurrent.futures`), no venv/dependency install needed.
Measures raw API serving capacity against a handful of representative
authenticated GET endpoints (`/healthz`, list requisitions, list candidates,
`/me`) — deliberately not the AI-gateway or sandbox-runner paths, whose real
latency (a Claude API round-trip; spinning up an isolated process) is a
different thing to characterize than millisecond-scale CRUD reads, and
mixing them into one percentile distribution would mislead more than it
informs.

Baseline captured on this session's dev machine (single `docker compose`
instance — one API container, one Postgres, no horizontal scaling; treat as
a relative baseline for regression-spotting, not a production capacity
number for a different host): at concurrency 20, ~190 req/s, zero errors,
p99 latency 107–386ms across the four endpoints. At concurrency 60,
throughput rose to ~290 req/s, still zero errors, but p99 latency rose to
545ms–1.6s — the service degrades gracefully (no failures) rather than
falling over, but individual request latency is clearly where the ceiling
shows up first on a single instance. Not yet done: a sustained-load run
(minutes, not seconds), a realistic traffic-mix profile, and a run against
a production-shaped (multi-instance, real hardware) deployment — this is a
first data point, not a capacity-planning number.

## Model operations

Model inventory, licences, swap procedure: see MODEL_CARD.md (populated at M3).
GPU capacity dashboard and concurrency governor: pending M3/M8.

## Backup & restore

pgBackRest + MinIO versioning with a scripted restore drill: pending M12.
Dev-only reset: `docker compose down --volumes`.

## Incident response

Pending M12 (severity ladder, on-call rotation, comms templates). Until then:
single-operator project; treat any `readyz` non-200 as a page-worthy event.
