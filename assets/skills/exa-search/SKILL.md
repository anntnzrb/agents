---
name: exa-search
description: Use Exa for deep web research, full-page retrieval, and source-backed synthesis.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Exa Search

Use Exa directly over HTTP through the bundled cross-platform Python CLI.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

Credential check policy: run the documented CLI entrypoint first; it auto-loads a skill-local `.env` using the lookup order below. Only report missing credentials if the CLI itself fails after that lookup.

## When to use

- Deeper web research with richer retrieval than lightweight search
- Fetching full-page contents from known URLs
- Grounded answer generation from web results
- Exa research mode for bigger synthesis tasks

## Quick start

```text
uv run --script <skill-dir>/scripts/cli.py search "best sqlite backup strategy" 5
uv run --script <skill-dir>/scripts/cli.py contents https://sqlite.org/backup.html
uv run --script <skill-dir>/scripts/cli.py answer "What is the capital of France?"
uv run --script <skill-dir>/scripts/cli.py research "Summarize the current state of OpenTelemetry in the Java ecosystem" exa-research
```

## Credentials

- Keep `.env` beside this skill
- CLI lookup order:
  - `EXA_SEARCH_ENV_FILE`
  - skill `.env`
  - `$SKILLS_DIR/exa-search/.env`
  - nearest ancestor `skills/exa-search/.env`
- Tracked template: `.env.example`

## Failure handling

- If a CLI run says `EXA_API_KEY required`, retry once with the documented `uv run --script` command; do not assume the parent shell env is authoritative
- If env loading still fails, set `EXA_SEARCH_ENV_FILE` to the skill-local `.env` dynamically from the skill path rather than hard-coding a home directory
- Distinguish env lookup failures from provider failures:
  - `EXA_API_KEY required` means local env discovery failed
  - HTTP `401`, `402`, `403`, or similar means the API responded and the key/account/quota is the issue
- When the API responds with an auth/billing/quota error, report that explicitly instead of claiming the skill lacks credentials

## Notes

- Auth header: `x-api-key: $EXA_API_KEY`
- `search` is the best default entrypoint
- Use `contents` when you already know the target URL(s)
- Use `post` for advanced payloads not covered by convenience wrappers
- For code-specific public usage patterns, prefer `grep-app`, `gh`, and `context7` before forcing Exa

## Raw examples

```text
uv run --script <skill-dir>/scripts/cli.py post /search '{"query":"rust async channels","numResults":5}'
uv run --script <skill-dir>/scripts/cli.py post /contents '{"urls":["https://example.com/article"]}'
uv run --script <skill-dir>/scripts/cli.py post /answer '{"query":"What is Bun?"}'
```

## Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```

## Query templates

See `assets/query-templates.json`.

## Required follow-up reads

|Need|Read|When|
|---|---|---|
|HTTP endpoints and payload routing|`references/http.md`|Advanced endpoint or raw payload work|
|Reusable query shapes|`assets/query-templates.json`|Constructing a supported CLI request|
