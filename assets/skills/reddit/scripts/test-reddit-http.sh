#!/bin/sh
set -eu

UA="${REDDIT_USER_AGENT:-agents-reddit-test/1.0}"
BASE="${REDDIT_BASE_URL:-https://www.reddit.com}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing binary: $1" >&2
    exit 1
  }
}

need curl
need jq
need rg

fetch() {
  curl -fsSL -A "$UA" "$@"
}

echo "== browse =="
fetch "$BASE/r/programming/hot.json?limit=2" | jq '{kind, count: (.data.children|length)}'

echo "== search =="
fetch "$BASE/search.json?q=rust&sort=relevance&t=month&limit=2" | jq '{kind, count: (.data.children|length)}'

echo "== user =="
fetch "$BASE/user/spez/about.json" | jq '{kind, name: .data.name}'

echo "== comments =="
post_url="$(fetch "$BASE/r/programming/hot.json?limit=1" | jq -r '.data.children[0].data.permalink')"
fetch "${BASE}${post_url%.json}.json?limit=5" | jq '.[0].kind, .[1].kind'

echo "== skill content =="
rg -n 'Define `reddit` once per shell|reddit browse all hot limit=10|reddit user-analysis' assets/skills/reddit/SKILL.md >/dev/null

echo "ok"
