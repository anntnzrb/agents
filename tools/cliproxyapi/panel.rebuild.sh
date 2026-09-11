#!/bin/sh
# Rebuild the CLIProxyAPI management panel asset.
#
# The panel is upstream main plus two local layers:
#   1. tools/cliproxyapi/panel.patch  — the generic quota-card framework
#      (applied with a 3-way merge so upstream drift surfaces as conflicts)
#   2. tools/cliproxyapi/quota-cards.ts — the card definitions, copied into
#      src/utils/quota/custom/cards.ts before the build
#
# Upstream tracking: the default ref is `main` (latest). Export PANEL_REF to
# pin a tag, branch, or commit. BASE is the commit the patch was generated
# against; it keeps the 3-way merge preimage available on shallow clones.
#
# Requires git and bun on PATH.

set -eu

REPO="https://github.com/router-for-me/Cli-Proxy-API-Management-Center"
REF="${PANEL_REF:-main}"
BASE="ed5f1c48e11ba7335f1e8f676f228c280196af85"
OUT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CARDS="$OUT_DIR/quota-cards.ts"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone --depth 1 "$REPO" "$WORK/panel"
git -C "$WORK/panel" fetch --depth 1 origin "$REF"
git -C "$WORK/panel" checkout --detach FETCH_HEAD
# Fetch the patch preimage so `git apply --3way` can merge across upstream drift.
if [ "$(git -C "$WORK/panel" rev-parse HEAD)" != "$BASE" ]; then
	git -C "$WORK/panel" fetch --depth 1 origin "$BASE"
fi

git -C "$WORK/panel" apply --3way "$OUT_DIR/panel.patch"
cp "$CARDS" "$WORK/panel/src/utils/quota/custom/cards.ts"

cd "$WORK/panel"
bun install --frozen-lockfile
bun run build
cp dist/index.html "$OUT_DIR/panel.html"
echo "wrote $OUT_DIR/panel.html"
