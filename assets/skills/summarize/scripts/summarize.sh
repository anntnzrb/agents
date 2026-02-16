#!/usr/bin/env bash
set -euo pipefail

# Stable wrapper for the summarize CLI package.
exec bun x @steipete/summarize "$@"
