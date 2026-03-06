#!/usr/bin/env bash
set -euo pipefail

UA="${REDDIT_USER_AGENT:-agents-reddit-test/1.0}"
BASE="${REDDIT_BASE_URL:-https://www.reddit.com}"

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
HELPER="$SCRIPT_DIR/reddit.sh"
DEFAULT_ENV="$SKILL_DIR/.env"

if [ -z "${REDDIT_ENV_FILE:-}" ] && [ -f "$DEFAULT_ENV" ]; then
  export REDDIT_ENV_FILE="$DEFAULT_ENV"
fi

export REDDIT_USER_AGENT="$UA"
export REDDIT_BASE_URL="$BASE"

bash -n "$HELPER"
# shellcheck source=/dev/null
. "$HELPER"

echo "== browse =="
reddit browse programming hot limit=2 | jq '{kind, count: (.data.children | length)}'

echo "== search =="
reddit search "rust" sort=relevance time=month limit=2 | jq '{kind, count: (.data.children | length)}'

echo "== user =="
reddit user spez | jq '{kind, name: .data.name}'

echo "== comments =="
post_url="$(reddit browse programming hot limit=1 | jq -r '.data.children[0].data.permalink')"
reddit post-url "${BASE}${post_url}" comment_limit=5 | jq '.[0].kind, .[1].kind'

echo "== glossary =="
reddit explain karma | jq -e '.term == "karma"' >/dev/null

echo "ok"
