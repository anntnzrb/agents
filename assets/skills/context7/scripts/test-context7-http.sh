#!/usr/bin/env bash
set -euo pipefail

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing binary: $1" >&2
    exit 1
  }
}

need bash
need awk
need curl
need jq

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SKILL_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
SKILL_MD="$SKILL_DIR/SKILL.md"
DEFAULT_ENV="$SKILL_DIR/.env"

if [ -z "${CONTEXT7_ENV_FILE:-}" ] && [ -f "$DEFAULT_ENV" ]; then
  export CONTEXT7_ENV_FILE="$DEFAULT_ENV"
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
awk '/^```bash$/{flag=1;next}/^```$/{if(flag){exit}}flag' "$SKILL_MD" > "$tmp"
bash -n "$tmp"
# shellcheck source=/dev/null
. "$tmp"

echo "== search =="
context7 search react "hooks useState" | jq '{results: (.results | length), first_id: .results[0].id}'

echo "== docs =="
docs_tmp="$(mktemp)"
trap 'rm -f "$tmp" "$docs_tmp"' EXIT
context7 docs /vercel/next.js "app router" > "$docs_tmp"
awk 'NR <= 5 { print }' "$docs_tmp"

echo "ok"
