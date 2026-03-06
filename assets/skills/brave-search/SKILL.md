---
name: brave-search
description: "Fallback search via the Brave Search HTTP API. Use for quick lookups, recency checks, images/videos/local results, and lightweight web research when Exa isn't ideal."
---

# Brave Search

Use Brave Search directly over HTTP with `curl`; no mcporter needed.

## Required shell helper

Source the bash helper from this skill once per shell:

```bash
source "${SKILLS_DIR:-skills}/brave-search/scripts/brave-search.sh"
```

If `SKILLS_DIR` is unavailable, source the same file from your local `skills/` checkout.

Then use `brave-search <subcommand>` everywhere below.

## When to use

- Fast scoping / quick lookups
- Recency-sensitive news checks
- Image / video / local search
- Lightweight web research before escalating to Exa

## Quick start

```bash
brave-search web "rust async tutorial" count=5 summary=1
brave-search news "typescript 5.9" count=5 freshness=pd
brave-search local "coffee near times square" count=5
brave-search image "saturn v launch" count=10
brave-search video "bun runtime benchmark" count=10
```

## Summaries

Brave's older summarizer flow is still reachable directly:

```bash
key="$(brave-search summarizer-key "what is the second highest mountain" count=5)"
brave-search summarize "$key" inline_references=true entity_info=1
```

Use `brave-search raw /summarizer/title key="$key"` or other `/summarizer/*` paths for specialized endpoints.

## Credentials

- Keep `.env` beside this skill.
- Helper lookup order:
  - `BRAVE_SEARCH_ENV_FILE`
  - `$SKILLS_DIR/brave-search/.env`
  - nearest ancestor `skills/brave-search/.env`
- Tracked template: `.env.example`

## Notes

- Auth header: `X-Subscription-Token: $BRAVE_API_KEY`
- Pass optional query params as `key=value` pairs after the main argument.
- Useful params: `count=`, `freshness=`, `country=`, `search_lang=`, `ui_lang=`, `safesearch=`, `summary=1`
- `summary=1` on web search returns a summarizer key in the search response; fetch the full summary separately.
- Prefer Exa for deeper multi-source synthesis.

## Validation

```bash
./scripts/test-brave-http.sh
```

## Query templates

See `assets/query-templates.json`.

## Reference

See `reference.md`.
