#!/bin/sh
# agents-managed-wrapper:v1
set -eu
exec '<executable>' --config '<configPath>' "$@"
