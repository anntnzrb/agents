---
name: grep-app
description: "Use when public GitHub code examples or real-world API and configuration usage must be found through Grep.app."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Grep.app

Use Grep.app directly over HTTP through the bundled cross-platform Python CLI.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

Environment check policy: do not treat an unset `GREP_APP_BASE_URL` in the parent shell as a readiness failure. It is only an optional override; the skill works with its default base URL.

## When to use

- Real usage patterns for APIs, config, and framework code
- Public GitHub code only
- Literal search first; regex when needed

## Quick start

```text
uv run --script <skill-dir>/scripts/cli.py search "useState(" f.lang=TypeScript
uv run --script <skill-dir>/scripts/cli.py search "errgroup.WithContext(" f.repo=golang/sync
uv run --script <skill-dir>/scripts/cli.py regex "useState\\(" f.lang=TypeScript
```

## Useful filters

Pass Grep.app filters as query params:

- `f.repo=owner/repo`
- `f.path=src/`
- `f.lang=TypeScript`
- `case=true`
- `words=true`

## Environment

- Tracked template: `.env.example`
- Optional override: `GREP_APP_BASE_URL`

## Failure handling

- `grep-app` does not use a skill-local API key in this helper flow, so there is no `.env` credential-loading step to debug by default
- Distinguish invocation issues from service issues:
  - usage errors mean local invocation is wrong
  - HTTP `429` means Grep.app rate-limited the request
  - other HTTP failures mean the service or endpoint responded with an error, not that the helper failed to initialize
- If `429` appears, report it as rate limiting and either retry later or fall back to another research route such as `context7`, `gh`, or `exa-search`

## Notes

- Public GitHub repos only
- `search` is literal by default
- `regex` sets `regexp=true` automatically
- Grep.app returns HTML snippets inside JSON; extract metadata like repo/path first
- Check licenses before reusing copied code

## Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```

## Query templates

See `assets/query-templates.json`.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| HTTP parameters and response caveats | `references/http.md` | Advanced filters or response interpretation |
| Reusable query shapes | `assets/query-templates.json` | Constructing a supported CLI request |
