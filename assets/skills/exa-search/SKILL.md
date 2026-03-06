---
name: exa-search
description: "Primary search via Exa's HTTP API. Use for deeper web research, full-page content retrieval, answer generation, and richer synthesis when lightweight search is not enough."
---

# Exa Search

Use Exa directly over HTTP with `curl`; no mcporter needed.

## Required shell helper

Source the bash helper from this skill once per shell:

```bash
source "${SKILLS_DIR:-skills}/exa-search/scripts/exa-search.sh"
```

If `SKILLS_DIR` is unavailable, source the same file from your local `skills/` checkout.

Then use `exa-search <subcommand>` everywhere below.

## When to use

- Deeper web research with richer retrieval than lightweight search
- Fetching full-page contents from known URLs
- Grounded answer generation from web results
- Exa research mode for bigger synthesis tasks

## Quick start

```bash
exa-search search "best sqlite backup strategy" 5
exa-search contents https://sqlite.org/backup.html
exa-search answer "What is the capital of France?"
exa-search research "Summarize the current state of OpenTelemetry in the Java ecosystem" exa-research
```

## Credentials

- Keep `.env` beside this skill.
- Helper lookup order:
  - `EXA_SEARCH_ENV_FILE`
  - `$SKILLS_DIR/exa-search/.env`
  - nearest ancestor `skills/exa-search/.env`
- Tracked template: `.env.example`

## Notes

- Auth header: `x-api-key: $EXA_API_KEY`
- `search` is the best default entrypoint.
- Use `contents` when you already know the target URL(s).
- Use `post` for advanced payloads not covered by convenience wrappers.
- For code-specific public usage patterns, prefer `grep-app`, `gh`, and `context7` before forcing Exa.

## Raw examples

```bash
exa-search post /search '{"query":"rust async channels","numResults":5}'
exa-search post /contents '{"urls":["https://example.com/article"]}'
exa-search post /answer '{"query":"What is Bun?"}'
```

## Validation

```bash
./scripts/test-exa-http.sh
```

## Query templates

See `assets/query-templates.json`.

## Reference

See `reference.md`.
