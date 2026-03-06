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

if [ -z "${BRAVE_SEARCH_ENV_FILE:-}" ] && [ -f "$DEFAULT_ENV" ]; then
  export BRAVE_SEARCH_ENV_FILE="$DEFAULT_ENV"
fi

if [ -z "${BRAVE_API_KEY:-${BRAVE_SEARCH_API_KEY:-}}" ] && [ ! -f "${BRAVE_SEARCH_ENV_FILE:-$DEFAULT_ENV}" ]; then
  echo "skip: BRAVE_API_KEY missing; copy .env.example to .env or export BRAVE_API_KEY" >&2
  exit 0
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
awk '/^```bash$/{flag=1;next}/^```$/{if(flag){exit}}flag' "$SKILL_MD" > "$tmp"
bash -n "$tmp"
# shellcheck source=/dev/null
. "$tmp"

echo "== web =="
brave-search web "rust programming language" count=1 | jq '{web_results: (.web.results | length), first_url: .web.results[0].url}'

echo "== news =="
brave-search news "typescript" count=1 freshness=pm | jq '{results: (.results | length), first_title: .results[0].title}'

echo "ok"
