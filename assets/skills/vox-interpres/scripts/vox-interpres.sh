#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
SKILL_DIR=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'vox-interpres: uv not found in PATH' >&2
  exit 127
fi

exec uv run --project "$SKILL_DIR" vox-interpres "$@"
