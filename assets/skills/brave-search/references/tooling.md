# Tooling Reference

The Brave Search skill exposes one cross-platform Python CLI:

```text
uv run --script <skill-dir>/scripts/cli.py <command> [args ...]
```

## Commands at a glance

| Command | Output | Notes |
| --- | --- | --- |
| `web` | compact JSON envelope | defaults: `count=5`, `result_filter=web` |
| `news` | compact JSON envelope | default: `count=5` |
| `local` | compact JSON envelope | default: `count=5` |
| `image` | compact JSON envelope | default: `count=10` |
| `video` | compact JSON envelope | default: `count=10` |
| `summarizer-key` | raw key on stdout / compact JSON error on stderr | legacy; rc=1 when Brave declines to summarize |
| `summarize` | upstream passthrough | legacy; needs a key from `summarizer-key` |
| `raw` | upstream passthrough | for any provider path (`/web/search`, `/summarizer/*`, …) |

## Common flags

- `count=<1..20>` — capped and pre-validated; bad values → rc=2, no network call.
- `raw=1` (or bare `raw`) — skip defaults and compact projection; stream upstream bytes.
- Endpoint-specific params (`freshness=`, `country=`, `search_lang=`, `ui_lang=`, `safesearch=`, `result_filter=`) pass straight through.

## Error envelope

HTTP and network errors emit a one-line compact JSON envelope on stderr with `error.provider`, `error.status`, `error.message`, `error.body_bytes`, `error.body_preview`, `error.body_truncated`. See `../../reference.md` for the full shape.
