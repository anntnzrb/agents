#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SKILL_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

if [ -f "$SKILL_DIR/.env" ]; then
  case "$-" in
    *a*) _had_allexport=1 ;;
    *) _had_allexport=0 ;;
  esac
  set -a
  # shellcheck source=/dev/null
  . "$SKILL_DIR/.env"
  if [ "$_had_allexport" -eq 0 ]; then
    set +a
  fi
fi

exec uv run --project "$SKILL_DIR" flight-live "$@"
