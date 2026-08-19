---
name: brave-search
description: "Use when a quick current web, image, video, news, or local-result search is needed."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Brave Search

Direct HTTP access via bundled cross-platform Python CLI.

## Entry point

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

`<skill-dir>` = this skill directory. Do not use shell sourcing, executable bits, or shebang dispatch.

Credential check: MUST run the documented CLI entrypoint first. It auto-loads the skill-local `.env` in this order; report missing credentials only if the CLI fails after lookup:

1. `BRAVE_SEARCH_ENV_FILE`
2. skill `.env`
3. `$SKILLS_DIR/brave-search/.env`
4. nearest ancestor `skills/brave-search/.env`

Keep `.env` beside this skill. Tracked template: `.env.example`.

## Use

- Fast scoping / quick lookups
- Recency-sensitive news checks
- Image / video / local search
- Lightweight web research before escalating to Exa

## Quick start

Endpoint commands return compact, agent-shaped JSON by default: `{type, query, count, results, [more_results_available]}`. `raw=1` streams the unchanged upstream payload.

```text
uv run --script <skill-dir>/scripts/cli.py web "rust async tutorial" result_filter=web
uv run --script <skill-dir>/scripts/cli.py news "typescript 5.9" freshness=pd
uv run --script <skill-dir>/scripts/cli.py local "coffee near times square"
uv run --script <skill-dir>/scripts/cli.py image "saturn v launch"
uv run --script <skill-dir>/scripts/cli.py video "bun runtime benchmark"
```

Defaults without overrides:
- `web`, `news`, `local`: `count=5`
- `image`, `video`: `count=10`
- `web` only: `result_filter=web`, skipped when `result_filter=` or `raw=1` is passed

`count` hard cap: `1..20`. Invalid values (`count=50`, `count=abc`, `count=5.5`, …) are rejected with rc=2 before network access.

## Summarizer (legacy)

The older summarizer remains available for backward access but is **not recommended**. Prefer compact endpoints; use it only when you already have a key.

```text
uv run --script <skill-dir>/scripts/cli.py summarizer-key "what is the second highest mountain"
uv run --script <skill-dir>/scripts/cli.py summarize <summary-key> inline_references=true
```

`summarizer-key`: rc=1, no network retry, when Brave declines to summarize. `summarize` and `raw` remain raw passthrough for callers needing the unprojected payload.

## Failure handling

- `BRAVE_API_KEY required`: retry once with the documented `uv run --script` command; do not assume the parent-shell environment is authoritative.
- If env loading still fails, set `BRAVE_SEARCH_ENV_FILE` dynamically from the skill path; never hard-code a machine-specific directory.
- Distinguish local env discovery from provider failure:
  - `BRAVE_API_KEY required`: local env discovery failed (rc=2).
  - HTTP `401`, `402`, `403`, `429`, or similar: API responded; key/account/quota/rate limit is the issue.
- HTTP and network failures emit one-line compact JSON on stderr with `error.provider`, `error.status`, `error.message`, `error.body_bytes`, `error.body_preview`, `error.body_truncated`; HTML bodies become plain text capped at ~500 chars. Network/parse errors: rc=1. HTTP errors: rc=22.
- Usage errors (missing args, bad count, missing API key): rc=2 with concise plain-text stderr, not the compact envelope.
- Report the actual HTTP failure mode; do not collapse it into “missing credentials”.

## Notes

- Auth header: `X-Subscription-Token: $BRAVE_API_KEY`
- Optional query params follow the main argument as `key=value` pairs.
- `raw=1` skips defaults and compact projection; `raw=0` and every other value are ignored.
- Useful params: `count=`, `freshness=`, `country=`, `search_lang=`, `ui_lang=`, `safesearch=`, `result_filter=` (web only).
- Prefer Exa for deeper multi-source synthesis.

## Need | Read | When

|Need|Read|When|
|---|---|---|
|Field-level projection, count cap, raw passthrough, error envelope shape|`reference.md`|You are writing code that consumes the compact JSON, or debugging a provider failure|
|Worked example commands and per-endpoint query templates|`assets/query-templates.json`|You want a copy-pasteable command or to seed a new template|
|High-level command layout and behavior summary|`SKILL.md` (this file)|You need to know what the skill does at a glance|
|Reference flows for human-style lookups|`references/flows.md`|You want a recipe for a multi-step lookup pattern|
|Future refactor concerns, expectations, and regression traps|`references/future-refactor.md`|You are planning a larger refactor or changing output/error contracts|
|Stale scaffolding that used to describe the old `search.ts` / `content.ts` helpers|`references/tooling.md`|Replaced by the compact CLI commands in this file: see "Quick start" above|

## Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```

## Query templates

See `assets/query-templates.json`.

## Reference

See `reference.md`.
