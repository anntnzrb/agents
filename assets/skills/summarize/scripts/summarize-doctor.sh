#!/usr/bin/env bash
set -euo pipefail

check_bin() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    printf "[ok]   %-12s %s\n" "$name" "$(command -v "$name")"
  else
    printf "[miss] %-12s\n" "$name"
  fi
}

check_env() {
  local name="$1"
  if [[ -n "${!name:-}" ]]; then
    printf "[ok]   %-24s set\n" "$name"
  else
    printf "[miss] %-24s\n" "$name"
  fi
}

echo "== binaries =="
check_bin bun
check_bin yt-dlp
check_bin ffmpeg
check_bin tesseract
check_bin whisper-cli
check_bin claude
check_bin codex
check_bin gemini
check_bin agent

echo
echo "== key env vars =="
check_env OPENAI_API_KEY
check_env ANTHROPIC_API_KEY
check_env GEMINI_API_KEY
check_env XAI_API_KEY
check_env Z_AI_API_KEY
check_env OPENROUTER_API_KEY
check_env NVIDIA_API_KEY
check_env FIRECRAWL_API_KEY
check_env APIFY_API_TOKEN
check_env FAL_KEY

config_path="${HOME}/.summarize/config.json"
echo
echo "== config =="
if [[ -f "$config_path" ]]; then
  echo "[ok]   ${config_path}"
else
  echo "[miss] ${config_path}"
fi

echo
echo "== summarize smoke =="
if command -v bun >/dev/null 2>&1; then
  bun x @steipete/summarize --version || true
fi
