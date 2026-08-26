#!/usr/bin/env bash
# Seeds the fixed demo/test recruiter account against a running dev API.
# Idempotent: a 409 (org or email already exists) is treated as success.
set -euo pipefail

API_URL="${AIVA_API_URL:-http://localhost:18000}"
ORG_NAME="${AIVA_DEMO_ORG:-AIVA Demo Org}"
ADMIN_EMAIL="${AIVA_DEMO_EMAIL:-demo.recruiter@aiva.test}"
ADMIN_PASSWORD="${AIVA_DEMO_PASSWORD:-AivaDemo#2026!}"

tmp_body="$(mktemp)"
trap 'rm -f "$tmp_body"' EXIT

response=$(curl -sS -o "$tmp_body" -w '%{http_code}' \
  -X POST "$API_URL/auth/register-org" \
  -H 'Content-Type: application/json' \
  -d "$(printf '{"organization_name":"%s","admin_email":"%s","admin_password":"%s"}' \
        "$ORG_NAME" "$ADMIN_EMAIL" "$ADMIN_PASSWORD")")
body=$(cat "$tmp_body")

if [[ "$response" == "201" ]]; then
  printf 'seeded demo account: %s\n' "$ADMIN_EMAIL"
elif [[ "$response" == "409" ]]; then
  printf 'demo account already present: %s\n' "$ADMIN_EMAIL"
else
  printf 'seed failed (HTTP %s): %s\n' "$response" "$body" >&2
  exit 1
fi

cat <<EOF

  Test credentials (web-recruiter login, port 15173):
    email:    $ADMIN_EMAIL
    password: $ADMIN_PASSWORD

EOF
