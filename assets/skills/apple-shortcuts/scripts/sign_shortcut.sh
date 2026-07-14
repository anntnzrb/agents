#!/usr/bin/env bash
# Shortcuts Playground for Codex: archive + sign a Shortcuts plist.
#
# Usage:
#   sign_shortcut.sh <input.xml> [--name "Final Name"] [--mode anyone|people-who-know-me] [--output-dir DIR]
#
# Defaults:
#   --mode        : $SHORTCUTS_PLAYGROUND_SIGNING_MODE, else "anyone"
#   --output-dir  : $SHORTCUTS_PLAYGROUND_OUTPUT_DIR; otherwise required
#   --name        : basename of the input file without extension

set -euo pipefail

INPUT=""
NAME=""
MODE="${SHORTCUTS_PLAYGROUND_SIGNING_MODE:-anyone}"
OUTPUT_DIR="${SHORTCUTS_PLAYGROUND_OUTPUT_DIR:-}"

usage() {
  cat <<'USAGE' >&2
Usage: sign_shortcut.sh <input.xml> [--name NAME] [--mode anyone|people-who-know-me] --output-dir DIR
USAGE
  exit 64
}

while [ $# -gt 0 ]; do
  case "$1" in
    --name)
      [ $# -ge 2 ] || usage
      NAME="$2"
      shift 2
      ;;
    --mode)
      [ $# -ge 2 ] || usage
      MODE="$2"
      shift 2
      ;;
    --output-dir)
      [ $# -ge 2 ] || usage
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      if [ -z "$INPUT" ]; then
        INPUT="$1"
        shift
      else
        printf 'Unexpected argument: %s\n' "$1" >&2
        usage
      fi
      ;;
  esac
done

[ -n "$INPUT" ] || usage

if [ ! -f "$INPUT" ]; then
  printf 'Input file not found: %s\n' "$INPUT" >&2
  exit 2
fi

if [ -z "$OUTPUT_DIR" ]; then
  printf 'Missing --output-dir (or SHORTCUTS_PLAYGROUND_OUTPUT_DIR); refusing an implicit write to ~/Documents.\n' >&2
  exit 64
fi

if [ "$MODE" != "anyone" ] && [ "$MODE" != "people-who-know-me" ]; then
  printf 'Invalid --mode: %s (expected "anyone" or "people-who-know-me")\n' "$MODE" >&2
  exit 64
fi

if ! command -v shortcuts >/dev/null 2>&1; then
  printf 'Apple shortcuts CLI not found on PATH; signing requires macOS Shortcuts.\n' >&2
  exit 127
fi

if [ -z "$NAME" ]; then
  BASENAME="$(basename "$INPUT")"
  NAME="${BASENAME%.*}"
fi

case "$NAME" in
  */*|*\\*|.|..)
    printf 'Invalid --name: shortcut names cannot contain path separators or dot path segments.\n' >&2
    exit 64
    ;;
esac

DATE_STAMP="$(date +%F)"
TIME_STAMP="$(date +%H%M%S)"
ARCHIVE_DIR="$OUTPUT_DIR/$DATE_STAMP"
ARCHIVE_FILE="$ARCHIVE_DIR/${NAME}-${TIME_STAMP}.xml"
SIGNED_PATH="$OUTPUT_DIR/${NAME}.shortcut"
# Golden Gate's shortcuts signer can reject otherwise valid plist inputs when
# the temporary filename has no relationship to the shortcut name. Preserve the
# requested shortcut stem in temp names, matching the Python stress-test signer.
TMP_SIGN_INPUT="$OUTPUT_DIR/${NAME}-sign-input-$$.shortcut"
TMP_SIGN_OUTPUT="$OUTPUT_DIR/${NAME}-sign-output-$$.shortcut"

cleanup() {
  rm -f "$TMP_SIGN_INPUT" "$TMP_SIGN_OUTPUT"
}
trap cleanup EXIT

mkdir -p "$ARCHIVE_DIR" "$OUTPUT_DIR"
cp "$INPUT" "$ARCHIVE_FILE"
cp "$INPUT" "$TMP_SIGN_INPUT"

set +e
shortcuts sign --mode "$MODE" --input "$TMP_SIGN_INPUT" --output "$TMP_SIGN_OUTPUT"
SIGN_STATUS=$?
set -e
if [ "$SIGN_STATUS" -eq 0 ]; then
  mv "$TMP_SIGN_OUTPUT" "$SIGNED_PATH"
else
  cp "$ARCHIVE_FILE" "$TMP_SIGN_INPUT"
  rm -f "$TMP_SIGN_OUTPUT"
  if plutil -lint "$TMP_SIGN_INPUT" >/dev/null 2>&1; then
    printf '\nshortcuts-playground: Apple shortcuts sign failed; retrying after binary plist conversion.\n' >&2
    if plutil -convert binary1 "$TMP_SIGN_INPUT" >/dev/null 2>&1; then
      set +e
      shortcuts sign --mode "$MODE" --input "$TMP_SIGN_INPUT" --output "$TMP_SIGN_OUTPUT"
      SIGN_STATUS_BINARY=$?
      set -e
      if [ "$SIGN_STATUS_BINARY" -eq 0 ]; then
        mv "$TMP_SIGN_OUTPUT" "$SIGNED_PATH"
        SIGN_STATUS=0
      else
        printf '\nshortcuts-playground: Apple shortcuts sign failed even after binary plist conversion. If validate_shortcut.py and plutil -lint both pass, retry outside Codex workspace-write sandbox restrictions or with Codex filesystem sandboxing set to full access before treating the plist as malformed.\n' >&2
        exit "$SIGN_STATUS_BINARY"
      fi
    fi
  fi
  if [ "$SIGN_STATUS" -ne 0 ]; then
    printf '\nshortcuts-playground: Apple shortcuts sign failed. If validate_shortcut.py and plutil -lint both pass, retry outside Codex workspace-write sandbox restrictions or with Codex filesystem sandboxing set to full access before treating the plist as malformed.\n' >&2
    exit "$SIGN_STATUS"
  fi
fi

printf '{"archive":"%s","signed":"%s","mode":"%s"}\n' "$ARCHIVE_FILE" "$SIGNED_PATH" "$MODE"
