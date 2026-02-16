---
name: summarize
description: Operate `@steipete/summarize` end-to-end via `bun x @steipete/summarize` for URL/file/media summarization, extract-only output, YouTube transcript and slide workflows, model/language/length tuning, CLI-backend routing (`--cli`), cache/config management, and `refresh-free` model maintenance. Use when users ask to summarize or extract content, transcribe audio/video, run slide extraction, tune summarize config/env keys, or troubleshoot summarize command failures.
---

# Summarize

Use this skill as an operator manual for the `@steipete/summarize` CLI.

## Core Rule

- Invoke summarize with `bun x @steipete/summarize ...`.
- Prefer the local wrapper `./scripts/summarize.sh ...` in this skill for consistency.
- Treat summarize as a black-box CLI. Do not inspect source code unless the user asks.

## Workflow

1. Identify intent.
- `summary`: summarize content.
- `extract`: extract raw content/transcript without LLM summary.
- `slides`: extract slide screenshots from video.
- `transcriber-setup`: print ONNX setup env vars.
- `refresh-free`: rebuild OpenRouter free preset.

2. Run a baseline command.
- Summary baseline: `./scripts/summarize.sh "<input>"`
- Extract baseline: `./scripts/summarize.sh "<input>" --extract`
- Slides baseline: `./scripts/summarize.sh slides "<video-url>"`

3. Apply mode-specific flags.
- Load `references/capabilities.md` for complete option surface.
- Load `references/recipes.md` for ready-to-run recipes.
- Load `references/config-and-env.md` for config/env setup.
- Load `references/help-snapshots.md` for exact live `--help` outputs by subcommand.
- Load `references/troubleshooting.md` for failure handling.

4. Verify result quality.
- For debugging, re-run with `--verbose`.
- For machine-readable output, use `--json`.
- Quote exact error text when reporting failures.

## Quick Command Map

- Main help: `./scripts/summarize.sh --help`
- Summarize: `./scripts/summarize.sh "https://example.com"`
- Extract only: `./scripts/summarize.sh "https://example.com" --extract --format md`
- YouTube transcript path: `./scripts/summarize.sh "<youtube-url>" --youtube auto`
- Slides in summary: `./scripts/summarize.sh "<youtube-url>" --slides --slides-ocr`
- Slides-only mode: `./scripts/summarize.sh slides "<youtube-or-video-url>" --render auto`
- ONNX helper: `./scripts/summarize.sh transcriber setup --model parakeet`
- Free preset refresh: `./scripts/summarize.sh refresh-free --set-default`

## Guardrails

- Use `--extract` when user asks for source text/markdown, not a summary.
- Use `--video-mode transcript` when user explicitly wants transcription-first for media URLs.
- Use `--model openrouter/...` only when user wants forced OpenRouter routing.
- Run `./scripts/summarize-doctor.sh` before deep troubleshooting.
- Prefer incremental tuning: first baseline command, then add one flag at a time.
