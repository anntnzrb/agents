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
HELPER="$SCRIPT_DIR/exa-search.sh"
DEFAULT_ENV="$SKILL_DIR/.env"

if [ -z "${EXA_SEARCH_ENV_FILE:-}" ] && [ -f "$DEFAULT_ENV" ]; then
  export EXA_SEARCH_ENV_FILE="$DEFAULT_ENV"
fi

if [ -z "${EXA_API_KEY:-${EXA_APIKEY:-}}" ] && [ ! -f "${EXA_SEARCH_ENV_FILE:-$DEFAULT_ENV}" ]; then
  echo "skip: EXA_API_KEY missing; copy .env.example to .env or export EXA_API_KEY" >&2
  exit 0
fi

bash -n "$HELPER"
# shellcheck source=/dev/null
. "$HELPER"

echo "== search =="
exa-search search "rust async" 1 | jq '{results: (.results | length), first_url: .results[0].url}'

echo "== contents =="
exa-search contents https://example.com | jq '{results: (.results | length), first_url: .results[0].url}'

echo "ok"
