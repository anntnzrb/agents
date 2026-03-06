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
HELPER="$SCRIPT_DIR/grep-app.sh"

bash -n "$HELPER"
# shellcheck source=/dev/null
. "$HELPER"

echo "== literal =="
grep-app search "useState(" f.lang=TypeScript | jq '{total: .hits.total, first_path: .hits.hits[0].path}'

echo "== regex =="
grep-app regex "useState\\(" f.lang=TypeScript | jq '{total: .hits.total, first_path: .hits.hits[0].path}'

echo "ok"
