#!/bin/sh
# agents-managed-wrapper:v1
set -eu
if [ ! -f '<runtimeHome>/sync-current/src/sync/cli.py' ]; then
  echo 'agents: sync runtime is missing; run sync from the agents repository' >&2
  exit 127
fi
exec python3 '<runtimeHome>/sync-current/src/sync/cli.py' launch '<sourceName>' -- "$@"
