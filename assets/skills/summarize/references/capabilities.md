# Summarize Capabilities

Complete command surface for `bun x @steipete/summarize`.

## Primary Invocation

- `bun x @steipete/summarize [options] [input]`
- `input`: URL, local file path, or `-` for stdin.

## Main Modes

- Summary mode: default behavior (extract + summarize).
- Extract mode: `--extract` (no summary LLM call).
- Slides-integrated summary: `--slides` (with optional OCR).
- Slides-only extraction: `slides <url>` subcommand.
- Transcriber setup helper: `transcriber setup`.
- Free model preset maintenance: `refresh-free`.

## Root Options (by category)

### Input and extraction

- `--youtube auto|web|no-auto|yt-dlp|apify`
- `--transcriber auto|whisper|parakeet|canary`
- `--video-mode auto|transcript|understand`
- `--firecrawl off|auto|always`
- `--format md|text`
- `--preprocess off|auto|always`
- `--markdown-mode off|auto|llm|readability`
- `--extract`
- `--max-extract-characters <count>`
- `--timestamps`

### Slides

- `--slides`
- `--slides-debug`
- `--slides-ocr`
- `--slides-dir <dir>`
- `--slides-scene-threshold <value>`
- `--slides-max <count>`
- `--slides-min-duration <seconds>`

### Model + output control

- `--model <id|preset|auto>`
- `--cli [claude|gemini|codex|agent]`
- `--length short|medium|long|xl|xxl|s|m|l|<chars>`
- `--max-output-tokens <count>`
- `--language|--lang <language>`
- `--prompt <text>`
- `--prompt-file <path>`
- `--force-summary`
- `--timeout <duration>`
- `--retries <count>`

### Caching + diagnostics + presentation

- `--no-cache`
- `--no-media-cache`
- `--cache-stats`
- `--clear-cache`
- `--json`
- `--stream auto|on|off`
- `--plain`
- `--no-color`
- `--theme aurora|ember|moss|mono`
- `--metrics off|on|detailed`
- `--verbose`
- `--debug`

## Subcommands

### `slides`

- Usage: `bun x @steipete/summarize slides [options] <url>`
- Purpose: extract slide screenshots from YouTube/direct video URL.
- Options:
  - `--slides-ocr`
  - `--slides-dir <dir>` / `-o, --output <dir>`
  - `--slides-scene-threshold <value>`
  - `--slides-max <count>`
  - `--slides-min-duration <seconds>`
  - `--render auto|kitty|iterm|none`
  - `--theme aurora|ember|moss|mono`
  - `--timeout <duration>`
  - `--no-cache`
  - `--json`
  - `--verbose|--debug`

### `transcriber setup`

- Usage: `bun x @steipete/summarize transcriber setup [--model parakeet|canary] [--theme <name>]`
- Purpose: print env vars/steps for local ONNX transcription.

### `refresh-free`

- Usage: `bun x @steipete/summarize refresh-free [--runs 2] [--smart 3] [--min-params 27b] [--max-age-days 180] [--set-default] [--verbose]`
- Purpose: regenerate `models.free` candidates in `~/.summarize/config.json`.

## Supported Inputs

- Web URLs
- YouTube URLs (`youtube.com`, `youtu.be`)
- Podcast URLs and RSS feeds
- Local files (text, PDF, image, audio, video)
- Remote media URLs
- stdin via `-` (text or binary, max ~50MB)

## Key Behavior Notes

- Short content may be returned as-is unless `--force-summary` is set.
- `--json` disables streaming and emits structured diagnostics.
- `--extract` for URL/path inputs; stdin + extract is not supported.
- `--model auto` performs candidate fallback and key-aware filtering.
- `--cli` routes through installed coding CLIs and can participate in auto mode.
