---
name: brave-search
description: Fallback search via the Brave Search HTTP API. Use for quick lookups, recency checks, images/videos/local results, and lightweight web research when Exa isn't ideal.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
disable-model-invocation: true
---

# Brave Search

Use Brave Search directly over HTTP through the bundled cross-platform Python CLI.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

Credential check policy: run the documented CLI entrypoint first; it auto-loads a skill-local `.env` using the lookup order below. Only report missing credentials if the CLI itself fails after that lookup.

## When to use

- Fast scoping / quick lookups
- Recency-sensitive news checks
- Image / video / local search
- Lightweight web research before escalating to Exa

## Quick start

```text
uv run --script <skill-dir>/scripts/cli.py web "rust async tutorial" count=5 summary=1
uv run --script <skill-dir>/scripts/cli.py news "typescript 5.9" count=5 freshness=pd
uv run --script <skill-dir>/scripts/cli.py local "coffee near times square" count=5
uv run --script <skill-dir>/scripts/cli.py image "saturn v launch" count=10
uv run --script <skill-dir>/scripts/cli.py video "bun runtime benchmark" count=10
```

## Summaries

Brave's older summarizer flow is still reachable directly:

```text
uv run --script <skill-dir>/scripts/cli.py summarizer-key "what is the second highest mountain" count=5
uv run --script <skill-dir>/scripts/cli.py summarize <summary-key> inline_references=true entity_info=1
```

Use `raw /summarizer/title key=<summary-key>` or other `/summarizer/*` paths for specialized endpoints.

## Credentials

- Keep `.env` beside this skill.
- CLI lookup order:
  - `BRAVE_SEARCH_ENV_FILE`
  - skill `.env`
  - `$SKILLS_DIR/brave-search/.env`
  - nearest ancestor `skills/brave-search/.env`
- Tracked template: `.env.example`

## Failure handling

- If a CLI run says `BRAVE_API_KEY required`, retry once with the documented `uv run --script` command; do not assume the parent shell env is authoritative.
- If env loading still fails, set `BRAVE_SEARCH_ENV_FILE` dynamically from the skill path rather than hard-coding a machine-specific directory.
- Distinguish env lookup failures from provider failures:
  - `BRAVE_API_KEY required` means local env discovery failed.
  - HTTP `401`, `402`, `403`, `429`, or similar means the API responded and the key/account/quota/rate limit is the issue.
- Report the actual HTTP failure mode instead of collapsing everything into “missing credentials”.

## Notes

- Auth header: `X-Subscription-Token: $BRAVE_API_KEY`
- Pass optional query params as `key=value` pairs after the main argument.
- Useful params: `count=`, `freshness=`, `country=`, `search_lang=`, `ui_lang=`, `safesearch=`, `summary=1`
- `summary=1` on web search returns a summarizer key in the search response; fetch the full summary separately.
- Prefer Exa for deeper multi-source synthesis.

## Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```

## Query templates

See `assets/query-templates.json`.

## Reference

See `reference.md`.
