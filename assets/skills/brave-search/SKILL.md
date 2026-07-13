---
name: brave-search
description: Use Brave Search for quick, current web, image, video, or local-result lookups.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
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

Endpoint commands return compact, agent-shaped JSON by default (envelope: `{type, query, count, results, [more_results_available]}`). Pass `raw=1` to stream the upstream payload unchanged.

```text
uv run --script <skill-dir>/scripts/cli.py web "rust async tutorial" result_filter=web
uv run --script <skill-dir>/scripts/cli.py news "typescript 5.9" freshness=pd
uv run --script <skill-dir>/scripts/cli.py local "coffee near times square"
uv run --script <skill-dir>/scripts/cli.py image "saturn v launch"
uv run --script <skill-dir>/scripts/cli.py video "bun runtime benchmark"
```

Defaults applied when no override is given:

- `web`, `news`, `local` → `count=5`
- `image`, `video` → `count=10`
- `web` only → `result_filter=web` (skipped if you pass `result_filter=` or `raw=1`)

Count is hard-capped at `1..20`. Bad values (`count=50`, `count=abc`, `count=5.5`, …) are rejected with rc=2 before any network call.

## Summarizer (legacy)

Brave's older summarizer flow is still reachable for backward access but is **not a recommended flow**. Prefer the default compact endpoints; reach for summarizer only when you have a key already.

```text
uv run --script <skill-dir>/scripts/cli.py summarizer-key "what is the second highest mountain"
uv run --script <skill-dir>/scripts/cli.py summarize <summary-key> inline_references=true
```

`summarizer-key` exits rc=1 (no network retry) when Brave declines to summarize the query. `summarize` and the `raw` command stay as raw passthrough for callers that need the unprojected payload.

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
  - `BRAVE_API_KEY required` means local env discovery failed (rc=2).
  - HTTP `401`, `402`, `403`, `429`, or similar means the API responded and the key/account/quota/rate limit is the issue.
- HTTP errors and network failures emit a one-line compact JSON envelope on stderr with `error.provider`, `error.status`, `error.message`, `error.body_bytes`, `error.body_preview` (HTML bodies are summarized to plain text, capped at ~500 chars), `error.body_truncated`. Network/parse errors return rc=1; HTTP errors return rc=22.
- Usage errors (missing args, bad count, missing API key) return rc=2 with a concise plain-text stderr message — not the compact error envelope.
- Report the actual HTTP failure mode instead of collapsing everything into "missing credentials".

## Notes

- Auth header: `X-Subscription-Token: $BRAVE_API_KEY`
- Pass optional query params as `key=value` pairs after the main argument. `raw=1` skips defaults and the compact projection; `raw=0` and any other value are ignored.
- Useful params: `count=`, `freshness=`, `country=`, `search_lang=`, `ui_lang=`, `safesearch=`, `result_filter=` (web only)
- Prefer Exa for deeper multi-source synthesis.

## Need | Read | When

| Need | Read | When |
| --- | --- | --- |
| Field-level projection, count cap, raw passthrough, error envelope shape | `reference.md` | You are writing code that consumes the compact JSON, or debugging a provider failure |
| Worked example commands and per-endpoint query templates | `assets/query-templates.json` | You want a copy-pasteable command or to seed a new template |
| High-level command layout and behavior summary | `SKILL.md` (this file) | You need to know what the skill does at a glance |
| Reference flows for human-style lookups | `references/flows.md` | You want a recipe for a multi-step lookup pattern |
| Future refactor concerns, expectations, and regression traps | `references/future-refactor.md` | You are planning a larger refactor or changing output/error contracts |
| Stale scaffolding that used to describe the old `search.ts` / `content.ts` helpers | `references/tooling.md` | Replaced by the compact CLI commands in this file — see "Quick start" above |

## Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```

## Query templates

See `assets/query-templates.json`.

## Reference

See `reference.md`.
