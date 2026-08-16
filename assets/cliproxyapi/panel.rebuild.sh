#!/bin/sh
# Rebuild the pinned CLIProxyAPI management panel asset (assets/cliproxyapi/panel.html)
# from upstream PR https://github.com/router-for-me/Cli-Proxy-API-Management-Center/pull/381.
# Run from anywhere; requires git and bun on PATH.
set -eu

REPO="https://github.com/router-for-me/Cli-Proxy-API-Management-Center"
HEAD="5d6ff13de6fd10e7cb20f0e6de1977cd4697bdae"
OUT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone --depth 1 "$REPO" "$WORK/panel"
git -C "$WORK/panel" fetch --depth 1 origin "$HEAD"
git -C "$WORK/panel" checkout --detach FETCH_HEAD

cd "$WORK/panel"
bun install --frozen-lockfile
bun run build
cp dist/index.html "$OUT_DIR/panel.html"
echo "wrote $OUT_DIR/panel.html"
