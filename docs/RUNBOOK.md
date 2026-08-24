# RUNBOOK

Living document. Sections marked **(pending Mx)** are declared gaps, not omissions.

## Development quickstart

```bash
docker compose up -d --wait
curl -f http://localhost:18000/healthz
curl -f http://localhost:18000/readyz
```

`readyz` returns 200 only when Postgres, Redis, and MinIO (including the
`aiva-artifacts` bucket) are reachable. The bucket is created by the one-shot
`minio-init` service.

## Services (dev)

| Service | Host port | Notes |
|---|---|---|
| API | 18000 | FastAPI, `/openapi.json` exposed, docs UI disabled |
| Postgres 16 | 15432 | user `aiva`, db `aiva`, pgvector + pg_trgm enabled |
| Redis 7 | 16379 | AOF on |
| MinIO | 19000 (console 19001) | bucket `aiva-artifacts` |
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

## Model operations

Model inventory, licences, swap procedure: see MODEL_CARD.md (populated at M3).
GPU capacity dashboard and concurrency governor: pending M3/M8.

## Backup & restore

pgBackRest + MinIO versioning with a scripted restore drill: pending M12.
Dev-only reset: `docker compose down --volumes`.

## Incident response

Pending M12 (severity ladder, on-call rotation, comms templates). Until then:
single-operator project; treat any `readyz` non-200 as a page-worthy event.
