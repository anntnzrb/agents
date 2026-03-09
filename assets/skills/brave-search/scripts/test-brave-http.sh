#!/usr/bin/env bash
set -euo pipefail

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing binary: $1" >&2
    exit 1
  }
}

need bash
need curl
need jq

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SKILL_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
HELPER="$SCRIPT_DIR/brave-search.sh"
DEFAULT_ENV="$SKILL_DIR/.env"

if [ -z "${BRAVE_SEARCH_ENV_FILE:-}" ] && [ -f "$DEFAULT_ENV" ]; then
  export BRAVE_SEARCH_ENV_FILE="$DEFAULT_ENV"
fi

if [ -z "${BRAVE_API_KEY:-${BRAVE_SEARCH_API_KEY:-}}" ] && [ ! -f "${BRAVE_SEARCH_ENV_FILE:-$DEFAULT_ENV}" ]; then
  echo "skip: BRAVE_API_KEY missing; copy .env.example to .env or export BRAVE_API_KEY" >&2
  exit 0
fi

bash -n "$HELPER"
# shellcheck source=/dev/null
. "$HELPER"

echo "== web =="
brave-search web "rust programming language" count=1 | jq '{web_results: (.web.results | length), first_url: .web.results[0].url}'

echo "== news =="
set +e
news_out="$(brave-search news "typescript" count=1 freshness=pm 2>&1)"
news_code=$?
set -e
if [ "$news_code" -eq 0 ]; then
  printf '%s\n' "$news_out" | jq '{results: (.results | length), first_title: .results[0].title}'
else
  printf '%s\n' "$news_out" >&2
  if printf '%s' "$news_out" | grep -q 'curl: (22).*429'; then
    echo "warn: news endpoint rate-limited; web search auth path already verified" >&2
  else
    exit "$news_code"
  fi
fi

echo "ok"
