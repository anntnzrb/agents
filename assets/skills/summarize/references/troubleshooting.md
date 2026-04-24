# Summarize Troubleshooting

Use this runbook when summarize commands fail.

## Quick triage

1. Capture exact command and exact stderr.
2. Re-run with `--verbose`.
3. If structured output helps, run with `--json`.
4. Run local doctor checks:

```text
uv run --script <skill-dir>/scripts/cli.py doctor
```

## Common failures

### 1) Missing API key / model unavailable

Symptoms:
- Provider auth errors.
- No model candidates in auto mode.

Actions:
- Verify env vars: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, etc.
- Force a known-working model:

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --model openai/gpt-5-mini
```

- If using OpenRouter, verify `OPENROUTER_API_KEY` and optional provider allowlist.

### 2) YouTube transcript failures

Symptoms:
- No transcript from `auto`/`web`.

Actions:
- Try explicit mode:

```text
uv run --script <skill-dir>/scripts/cli.py "<youtube-url>" --youtube yt-dlp --verbose
```

- Ensure `yt-dlp` is installed or set `YT_DLP_PATH`.
- Provide transcription fallback key (`OPENAI_API_KEY` or `FAL_KEY`).
- If captions should exist, test `--youtube apify` with `APIFY_API_TOKEN`.

### 3) Slides extraction problems

Symptoms:
- No slide images, poor slide segmentation, OCR missing.

Actions:
- Validate dependencies (`yt-dlp`, `ffmpeg`, optional `tesseract`).
- Tune thresholds:

```text
uv run --script <skill-dir>/scripts/cli.py slides "<url>" --slides-scene-threshold 0.2 --slides-max 12 --verbose
```

- Enable OCR only when needed:

```text
uv run --script <skill-dir>/scripts/cli.py "<url>" --slides --slides-ocr
```

### 4) Extraction quality is weak

Symptoms:
- Sparse web extraction text.

Actions:
- Test markdown extraction path:

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --extract --format md --markdown-mode readability --verbose
```

- Try Firecrawl fallback after setting `FIRECRAWL_API_KEY` in the environment:

```text
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --firecrawl always --extract --format md --verbose
```

### 5) Cache-related confusion

Symptoms:
- Repeated outputs seem stale.

Actions:

```text
uv run --script <skill-dir>/scripts/cli.py --cache-stats
uv run --script <skill-dir>/scripts/cli.py "https://example.com" --no-cache
uv run --script <skill-dir>/scripts/cli.py "https://example.com/video.mp4" --no-media-cache
```

## Escalation pattern

- Reproduce with smallest possible command.
- Pin model and input mode explicitly.
- Disable optional features (slides, OCR, markdown conversion) one by one.
- Report exact command + exact error + environment assumptions.
