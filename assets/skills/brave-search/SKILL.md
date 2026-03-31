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
The helper also auto-loads `.env` from its own skill directory, so absolute-path
`source` usage works from any current working directory.

Then use `brave-search <subcommand>` everywhere below.

Credential check policy: do not stop at `echo $BRAVE_API_KEY` in the parent shell. Always run the documented helper entrypoint first; it auto-loads a skill-local `.env` using the lookup order below. Only report missing credentials if `brave-search ...` itself fails after that lookup.

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
  - helper sibling `.env` resolved from `${BASH_SOURCE[0]}`
  - `$SKILLS_DIR/brave-search/.env`
  - nearest ancestor `skills/brave-search/.env`
- Tracked template: `.env.example`

## Failure handling

- If a helper run says `BRAVE_API_KEY required`, retry once with the helper itself; do not assume the parent shell env is authoritative.
- If you sourced the helper from an unusual location and env loading still fails, set `BRAVE_SEARCH_ENV_FILE` dynamically from the helper path rather than hard-coding a machine-specific directory.
- Distinguish env lookup failures from provider failures:
  - `BRAVE_API_KEY required` means local env discovery failed.
  - `curl: (22)` with HTTP `401`, `402`, `403`, `429`, or similar means the API responded and the key/account/quota/rate limit is the issue.
- Report the actual HTTP failure mode instead of collapsing everything into “missing credentials”.

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
