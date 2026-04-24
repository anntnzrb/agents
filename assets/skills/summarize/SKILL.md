---
name: summarize
description: Operate `@steipete/summarize` end-to-end via the bundled `uv run --script <skill-dir>/scripts/cli.py` wrapper, which delegates to `bun x @steipete/summarize`, for URL/file/media summarization, extract-only output, YouTube transcript and slide workflows, model/language/length tuning, CLI-backend routing (`--cli`), cache/config management, and `refresh-free` model maintenance. Use when users ask to summarize or extract content, transcribe audio/video, run slide extraction, tune summarize config/env keys, or troubleshoot summarize command failures.
---

# Summarize

Use this skill as an operator manual for the `@steipete/summarize` CLI.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch. The wrapper delegates non-`doctor` commands to `bun x @steipete/summarize ...` and preserves its exit code.

## Core Rule

- Invoke summarize through `uv run --script <skill-dir>/scripts/cli.py ...`.
- Treat summarize as a black-box CLI. Do not inspect source code unless the user asks.
- Do not claim credentials/config are missing from parent-shell env inspection alone; prove it with the real CLI path or `uv run --script <skill-dir>/scripts/cli.py doctor`, since config may also live outside the current shell.

## Workflow

1. Identify intent.
- `summary`: summarize content.
- `extract`: extract raw content/transcript without LLM summary.
- `slides`: extract slide screenshots from video.
- `transcriber-setup`: print ONNX setup env vars.
- `refresh-free`: rebuild OpenRouter free preset.

2. Run a baseline command.
- Summary baseline: `uv run --script <skill-dir>/scripts/cli.py "<input>"`
- Extract baseline: `uv run --script <skill-dir>/scripts/cli.py "<input>" --extract`
- Slides baseline: `uv run --script <skill-dir>/scripts/cli.py slides "<video-url>"`

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

- Main help: `uv run --script <skill-dir>/scripts/cli.py --help`
- Summarize: `uv run --script <skill-dir>/scripts/cli.py "https://example.com"`
- Extract only: `uv run --script <skill-dir>/scripts/cli.py "https://example.com" --extract --format md`
- YouTube transcript path: `uv run --script <skill-dir>/scripts/cli.py "<youtube-url>" --youtube auto`
- Slides in summary: `uv run --script <skill-dir>/scripts/cli.py "<youtube-url>" --slides --slides-ocr`
- Slides-only mode: `uv run --script <skill-dir>/scripts/cli.py slides "<youtube-or-video-url>" --render auto`
- ONNX helper: `uv run --script <skill-dir>/scripts/cli.py transcriber setup --model parakeet`
- Free preset refresh: `uv run --script <skill-dir>/scripts/cli.py refresh-free --set-default`

## Guardrails

- Use `--extract` when user asks for source text/markdown, not a summary.
- Use `--video-mode transcript` when user explicitly wants transcription-first for media URLs.
- Use `--model openrouter/...` only when user wants forced OpenRouter routing.
- Run `uv run --script <skill-dir>/scripts/cli.py doctor` before deep troubleshooting.
- Prefer incremental tuning: first baseline command, then add one flag at a time.
