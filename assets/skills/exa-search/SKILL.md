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
The helper also auto-loads `.env` from its own skill directory, so absolute-path
`source` usage works from any current working directory.

Then use `exa-search <subcommand>` everywhere below.

Credential check policy: do not stop at `echo $EXA_API_KEY` in the parent shell. Always run the documented helper entrypoint first; it auto-loads a skill-local `.env` using the lookup order below. Only report missing credentials if `exa-search ...` itself fails after that lookup.

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
  - helper sibling `.env` resolved from `${BASH_SOURCE[0]}`
  - `$SKILLS_DIR/exa-search/.env`
  - nearest ancestor `skills/exa-search/.env`
- Tracked template: `.env.example`

## Failure handling

- If a helper run says `EXA_API_KEY required`, retry once with the helper itself; do not assume the parent shell env is authoritative.
- If you sourced the helper from an unusual location and env loading still fails, set `EXA_SEARCH_ENV_FILE` to the skill-local `.env` dynamically from the helper path rather than hard-coding a home directory.
- Distinguish env lookup failures from provider failures:
  - `EXA_API_KEY required` means local env discovery failed.
  - `curl: (22)` with HTTP `401`, `402`, `403`, or similar means the API responded and the key/account/quota is the issue.
- When the API responds with an auth/billing/quota error, report that explicitly instead of claiming the skill lacks credentials.

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
