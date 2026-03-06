# Brave Search HTTP Reference

## Base URL

- `https://api.search.brave.com/res/v1`
- Auth header: `X-Subscription-Token: <BRAVE_API_KEY>`

## Credentials

Keep `.env` beside this skill and populate it from `.env.example`.

Supported lookup order in the shell helper:
- `BRAVE_SEARCH_ENV_FILE`
- `$SKILLS_DIR/brave-search/.env`
- nearest ancestor `skills/brave-search/.env`

Direct env vars still win:
- `BRAVE_API_KEY`
- legacy alias: `BRAVE_SEARCH_API_KEY`

## Main endpoints

### Web search
- `GET /web/search`
- Required param: `q`
- Common params: `count`, `offset`, `freshness`, `country`, `search_lang`, `ui_lang`, `safesearch`, `summary`

Example:

```bash
brave-search web "machine learning tutorials" count=5 freshness=pw
```

### News search
- `GET /news/search`
- Required param: `q`
- Common params: `count`, `freshness`, `country`, `search_lang`, `safesearch`

Example:

```bash
brave-search news "bun runtime" count=5 freshness=pd
```

### Local search
- `GET /local/search`
- Required param: `q`
- Common params: `count`, `country`, `search_lang`

Example:

```bash
brave-search local "greek restaurants in san francisco" count=5
```

### Image search
- `GET /images/search`
- Required param: `q`
- Common params: `count`, `country`, `search_lang`, `safesearch`

Example:

```bash
brave-search image "apollo 11" count=10 safesearch=strict
```

### Video search
- `GET /videos/search`
- Required param: `q`
- Common params: `count`, `freshness`, `country`, `search_lang`

Example:

```bash
brave-search video "zig build demo" count=10 freshness=pm
```

## Summarizer flow

Brave's legacy summarizer is a two-step flow:

1. Get a key from web search
2. Fetch the summary from `/summarizer/search`

```bash
key="$(brave-search summarizer-key "what is the second highest mountain")"
brave-search summarize "$key" inline_references=true entity_info=1
```

Common specialized endpoints:

- `/summarizer/search`
- `/summarizer/summary`
- `/summarizer/summary_streaming`
- `/summarizer/title`
- `/summarizer/enrichments`
- `/summarizer/followups`
- `/summarizer/entity_info`

Use `brave-search raw </path> key=<key> ...` for these.

## Notes

- Web search is the best default path.
- `summary=1` on web search returns a `summarizer.key` when Brave can generate a summary.
- Summarizer is deprecated in Brave's docs in favor of newer answer-oriented flows, but the HTTP endpoints still exist.
- Keep queries URL-safe by always using the shell helper, which uses `--data-urlencode`.

## Validation

```bash
./scripts/test-brave-http.sh
```
