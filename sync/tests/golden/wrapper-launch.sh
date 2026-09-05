#!/bin/sh
# agents-managed-wrapper:v1
set -eu
if [ ! -x '<runtimeHome>/sync-current/.venv/bin/python' ]; then
  echo 'agents: sync runtime is missing; run sync from the agents repository' >&2
  exit 127
fi
exec '<runtimeHome>/sync-current/.venv/bin/python' -m sync.cli launch '<sourceName>' -- "$@"
