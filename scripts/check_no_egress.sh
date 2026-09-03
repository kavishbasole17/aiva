#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALLOWLIST_FILE="$ROOT/infra/egress_allowlist.txt"

mapfile -t FILES < <(
  git -C "$ROOT" ls-files --cached --others --exclude-standard | while IFS= read -r f; do
    case "$f" in
      pnpm-lock.yaml | package-lock.json | yarn.lock | infra/egress_allowlist.txt | scripts/check_no_egress.sh)
        ;;
      *.md)
        ;;
      *)
        if grep -Iq . "$ROOT/$f" 2>/dev/null; then
          printf '%s\n' "$f"
        fi
        ;;
    esac
  done
)

violations=0

declare -a RULE_PATHS=()
declare -a RULE_PATTERNS=()
while IFS= read -r rule; do
  [[ -z "$rule" || "$rule" == \#* ]] && continue
  path_glob="${rule%%::*}"
  pattern="${rule#*::}"
  RULE_PATHS+=("$path_glob")
  RULE_PATTERNS+=("$pattern")
done <"$ALLOWLIST_FILE"

is_allowed() {
  local file="$1" line="$2"
  local i
  for i in "${!RULE_PATHS[@]}"; do
    if [[ "$file" == ${RULE_PATHS[$i]} ]] && [[ "$line" =~ ${RULE_PATTERNS[$i]} ]]; then
      return 0
    fi
  done
  return 1
}

for file in "${FILES[@]}"; do
  while IFS=: read -r lineno text; do
    [[ -z "$lineno" ]] && continue
    if ! is_allowed "$file" "$text"; then
      printf 'EGRESS VIOLATION %s:%s: %s\n' "$file" "$lineno" "$(printf '%s' "$text" | sed 's/^[[:space:]]*//')"
      violations=$((violations + 1))
    fi
  done < <(grep -nE 'https?://' "$ROOT/$file" || true)
done

if ((violations > 0)); then
  printf '\n%s egress violation(s). External URLs are banned; add reviewed exceptions to infra/egress_allowlist.txt only for internal/loopback references.\n' "$violations" >&2
  exit 1
fi

printf 'No egress violations. %s file(s) scanned.\n' "${#FILES[@]}"
