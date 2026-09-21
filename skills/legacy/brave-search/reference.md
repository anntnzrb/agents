# Brave Search HTTP Reference

Read this before consuming projected fields, raw payloads, or provider-error envelopes.

## Base URL

- `https://api.search.brave.com/res/v1`
- Auth header: `X-Subscription-Token: <BRAVE_API_KEY>`

## Credentials

Keep `.env` beside this skill and populate it from `.env.example`.

Supported lookup order in `scripts/cli.py`:

- `BRAVE_SEARCH_ENV_FILE`
- `$SKILLS_DIR/brave-search/.env`
- nearest ancestor `skills/brave-search/.env`

Direct env vars still win:

- `BRAVE_API_KEY`
- legacy alias: `BRAVE_SEARCH_API_KEY`

## Endpoint commands (compact by default)

`web`, `news`, `local`, `image`, and `video` all return compact agent-shaped JSON on stdout:

```json
{"type": "<cmd>", "query": "...", "count": <n>, "results": [...], "more_results_available": <bool>}
```

`more_results_available` is included only when Brave's response sets it on the `query` object. Defaults applied when the caller does not override:

| Command | Default `count` | Additional default |
| --- | --- | --- |
| `web` | `5` | `result_filter=web` (skipped if `result_filter=` is passed or `raw=1`) |
| `news` | `5` |: |
| `local` | `5` |: |
| `image` | `10` |: |
| `video` | `10` |: |

`count` is hard-capped at `1..20` (integer). Bad values are rejected with rc=2 before any network call. `raw=1` (or `raw` with no value) skips both defaults and the compact projection; the upstream bytes are streamed to stdout unchanged. `raw=0` and any other value is treated as the normal compact call.

### Web search

- `GET /web/search`
- Required param: `q`
- Common params: `count`, `offset`, `freshness`, `country`, `search_lang`, `ui_lang`, `safesearch`, `result_filter`
- Projected fields per result: `title`, `url`, `description`, `age`, `page_age`, `source` (from `profile.name`), plus `cluster` projected to `[{title,url,description}]` when present

Example:

```bash
brave-search web "machine learning tutorials" result_filter=web freshness=pw
```

### News search

- `GET /news/search`
- Required param: `q`
- Common params: `count`, `freshness`, `country`, `search_lang`, `safesearch`
- Projected fields per result: `title`, `url`, `description`, `age`, `page_age`, `source`

Example:

```bash
brave-search news "bun runtime" freshness=pd
```

### Local search

- `GET /local/search`
- Required param: `q`
- Common params: `count`, `country`, `search_lang`
- Projected fields per result: `title`, `url`, `description`, `age`, `page_age`, `source`

Example:

```bash
brave-search local "greek restaurants in san francisco"
```

### Image search

- `GET /images/search`
- Required param: `q`
- Common params: `count`, `country`, `search_lang`, `safesearch`
- Projected fields per result: `title`, `url`, `source`, `thumbnail_url`, `image_url`, `width`, `height`, `page_fetched`, `confidence`

Example:

```bash
brave-search image "apollo 11"
```

### Video search

- `GET /videos/search`
- Required param: `q`
- Common params: `count`, `freshness`, `country`, `search_lang`
- Projected fields per result: `title`, `url`, `description`, `age`, `page_age`, `duration`, `creator`, `publisher`, `thumbnail_url`

Example:

```bash
brave-search video "zig build demo"
```

## Raw passthrough

`raw` streams the upstream payload unchanged for any provider path. It is the right choice when you need fields the compact projection drops (e.g. `meta_url`, mixed-result lists, video tiles).

```bash
brave-search raw /web/search q=rust async result_filter=images
brave-search raw /summarizer/title key=<summary-key>
```

Use `raw=1` on an endpoint command to get the same upstream bytes for just that one call.

## Summarizer (legacy / experimental)

Brave's legacy summarizer is a two-step flow that is no longer the recommended path; prefer the default compact endpoints for new work. The flow is kept reachable for backward raw access:

1. Get a key from web search (with `summary=1`)
2. Fetch the summary from `/summarizer/search`

```bash
key="$(brave-search summarizer-key "what is the second highest mountain")"
brave-search summarize "$key" inline_references=true entity_info=1
```

`summarizer-key` returns rc=1 with a compact error JSON on stderr when Brave declines to summarize the query (e.g. no `summarizer.key` in the response). It does not silently succeed.

Common specialized endpoints:

- `/summarizer/search`
- `/summarizer/summary`
- `/summarizer/summary_streaming`
- `/summarizer/title`
- `/summarizer/enrichments`
- `/summarizer/followups`
- `/summarizer/entity_info`

Use `brave-search raw </path> key=<key> ...` for these.

## Error envelope

HTTP errors and network failures emit a one-line compact JSON envelope on stderr:

```json
{
  "error.provider": "brave-search",
  "error.status": 500,
  "error.message": "HTTP 500",
  "error.body_bytes": 1234,
  "error.body_preview": "summarized text",
  "error.body_truncated": false
}
```

- `error.status` is `null` for network/parse errors
- HTML bodies are detected and stripped to a plain-text summary before being placed in `error.body_preview`
- `error.body_preview` is capped at ~500 chars
- `error.body_truncated` is `true` when the upstream body was larger than the preview window
- HTTP errors return rc=22; network/parse errors return rc=1

Usage errors (missing args, bad count, missing API key) return rc=2 with a concise plain-text stderr message; not the compact error envelope.

## Notes

- Web search is the best default path
- `result_filter=web` is the right default for typical web search; override to `news`, `images`, or `videos` to scope the response to a single type
- Keep queries URL-safe by using `scripts/cli.py`, which encodes query parameters

## Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```
