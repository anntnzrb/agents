---
name: grep-app
description: "Search public GitHub code via Grep.app's HTTP API. Use for real-world usage examples, config snippets, and API syntax patterns."
---

# Grep.app

Use Grep.app directly over HTTP; no mcporter needed.

## Required shell helper

Source the bash helper from this skill once per shell:

```bash
source "${SKILLS_DIR:-skills}/grep-app/scripts/grep-app.sh"
```

If `SKILLS_DIR` is unavailable, source the same file from your local `skills/` checkout.

Then use `grep-app <subcommand>` everywhere below.

Environment check policy: do not treat an unset `GREP_APP_BASE_URL` in the parent shell as a readiness failure. It is only an optional override; the skill works with its default base URL.

## When to use

- Real usage patterns for APIs, config, and framework code
- Public GitHub code only
- Literal search first; regex when needed

## Quick start

```bash
grep-app search "useState(" f.lang=TypeScript
grep-app search "errgroup.WithContext(" f.repo=golang/sync
grep-app regex "useState\\(" f.lang=TypeScript
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

- `grep-app` does not use a skill-local API key in this helper flow, so there is no `.env` credential-loading step to debug by default.
- Distinguish helper issues from service issues:
  - shell/source/usage errors mean local invocation is wrong
  - `curl: (22)` with HTTP `429` means Grep.app rate-limited the request
  - other HTTP failures mean the service or endpoint responded with an error, not that the helper failed to initialize
- If `429` appears, report it as rate limiting and either retry later or fall back to another research route such as `context7`, `gh`, or `exa-search`.

## Notes

- Public GitHub repos only.
- `search` is literal by default.
- `regex` sets `regexp=true` automatically.
- Grep.app returns HTML snippets inside JSON; use `jq` to extract metadata like repo/path first.
- Check licenses before reusing copied code.

## Validation

```bash
./scripts/test-grep-app-http.sh
```

## Query templates

See `assets/query-templates.json`.

## Reference

See `reference.md`.
