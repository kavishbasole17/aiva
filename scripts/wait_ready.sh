#!/usr/bin/env bash
set -euo pipefail

READY_URL="${AIVA_READY_URL:-http://localhost:18000/readyz}"
TIMEOUT_SECONDS="${AIVA_READY_TIMEOUT:-120}"
deadline=$((SECONDS + TIMEOUT_SECONDS))

until curl -fsS "$READY_URL" >/dev/null 2>&1; do
  if ((SECONDS >= deadline)); then
    printf 'readiness timeout after %ss polling %s\n' "$TIMEOUT_SECONDS" "$READY_URL" >&2
    docker compose ps 2>/dev/null || true
    exit 1
  fi
  sleep 2
done

printf 'stack ready (%s)\n' "$READY_URL"
