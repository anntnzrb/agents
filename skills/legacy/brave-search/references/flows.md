# Example Flows

Multi-step lookup: web, news, image, video, or local.

All flows use:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

## Quick lookup

1. `web "<topic>"`: small default result set; `result_filter=web`.
2. Promising result → fetch via `raw <result-url>` (browser skill) or manually.

## Quick news scan

1. `news "<topic>"` with `freshness=pd`: past day.
2. Skim compact `results`; only fields actually used are present.

## Image/video shortlist

1. `image "<topic>"`: default `count=10`; thumbnails and source pages.
2. `video "<topic>"`: titles, durations, publishers.
3. Need upstream shape (e.g. raw `meta_url` or mixed-result fields) → rerun same command with `raw=1`.

## Provider failure triage

1. Compact stderr error JSON contains status, body byte count, summarized preview.
2. `error.status=null` → network/parse failure (rc=1), not provider rejection.
3. Set `error.status` → provider returned that code (rc=22); investigate key/quota/rate limits.
4. Bad count or missing args → rc=2, plain text; not JSON envelope.
