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
HELPER="$SCRIPT_DIR/context7.sh"
DEFAULT_ENV="$SKILL_DIR/.env"

if [ -z "${CONTEXT7_ENV_FILE:-}" ] && [ -f "$DEFAULT_ENV" ]; then
  export CONTEXT7_ENV_FILE="$DEFAULT_ENV"
fi

docs_tmp="$(mktemp)"
error_tmp="$(mktemp)"
trap 'rm -f "$docs_tmp" "$error_tmp"' EXIT
bash -n "$HELPER"
# shellcheck source=/dev/null
. "$HELPER"

echo "== search =="
context7 search react "hooks useState" | jq '{results: (.results | length), first_id: .results[0].id}'

echo "== docs =="
context7 docs /vercel/next.js "app router" > "$docs_tmp"
awk 'NR <= 5 { print }' "$docs_tmp"

echo "== not found =="
if context7 docs /nope/not-real "app router" >/dev/null 2>"$error_tmp"; then
  echo "expected docs lookup to fail" >&2
  exit 1
fi
awk 'NR == 1 { print }' "$error_tmp"
if ! awk 'index($0, "not found") { found=1 } END { exit found ? 0 : 1 }' "$error_tmp"; then
  echo "expected helpful not-found error" >&2
  awk '{ print }' "$error_tmp" >&2
  exit 1
fi

echo "ok"
