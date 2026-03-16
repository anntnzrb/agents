---
name: context7
description: "Retrieve up-to-date library/API docs and code examples via the Context7 HTTP API. Use for library-specific questions, setup/config steps, code generation, and verifying current APIs."
---

# Context7

Use Context7 for version-specific docs and code examples. Prefer direct HTTP via `curl`

## Required shell helper

Source the bash helper from this skill once per shell:

```bash
source "${SKILLS_DIR:-skills}/context7/scripts/context7.sh"
```

If `SKILLS_DIR` is unavailable, source the same file from your local `skills/` checkout.

Then use `context7 <subcommand>` everywhere below.

Credential check policy: do not stop at `echo $CONTEXT7_API_KEY` in the parent shell. Always run the documented helper entrypoint first; it auto-loads a skill-local `.env` using the lookup order below. The API key is optional for basic usage, so only report a credential problem if the real command still fails or the user specifically needs higher-rate access.

## Workflow

1. If you do not know the library ID, search first.
2. Inspect the top matches by `title`, `description`, and `totalSnippets`.
3. Fetch docs with `context7 docs <library-id> <query>`.
4. Use `context7 json ...` only when structured parsing is needed.

## Quick start

```bash
# Find likely matches
context7 search react "hooks useState" \
  | jq '.results[:5] | map({id, title, description, totalSnippets})'

# Grab the top library ID directly
context7 id react "hooks useState"

# Fetch readable docs
context7 docs /vercel/next.js "app router server actions"

# Fetch structured JSON when you need metadata/snippets
context7 json /fastapi/fastapi "dependency injection"
```

## Credentials

- API key is optional but recommended for higher rate limits.
- Keep `.env` beside this skill.
- Helper lookup order:
  - `CONTEXT7_ENV_FILE`
  - `$SKILLS_DIR/context7/.env`
  - nearest ancestor `skills/context7/.env`
- Tracked template: `.env.example`
- Header used when present: `Authorization: Bearer <key>`

## Notes

- If you already know the library ID (`/org/project`, `/org/project/version`, or `/websites/...`), skip search.
- `docs` and `json` accept library IDs with or without a leading `/`; examples keep the canonical slash form.
- Prefer exact title/source matches; use higher `totalSnippets` as a tiebreaker, not the only signal.
- `docs` uses `type=txt` because it is easier to read in agent output.
- Public endpoint works without an API key for basic usage; expect lower rate limits.
- Override `CONTEXT7_BASE_URL` if you need to point at a different host.
- When a key is present, the helper sends `Authorization: Bearer`, uses `--data-urlencode` for safe queries, and surfaces API error messages instead of raw curl HTTP failures.
- `id` uses `jq`; if `jq` is unavailable, inspect `search` output manually.

## Common examples

```bash
# React hooks
context7 id react "hooks useState"
context7 docs /websites/react_dev "useState"

# Next.js routing
context7 id nextjs "routing app router"
context7 docs /vercel/next.js "app router"

# FastAPI dependencies
context7 id fastapi "dependencies dependency injection"
context7 docs /fastapi/fastapi "dependency injection"
```

## Validation

```bash
./scripts/test-context7-http.sh
```

## Query templates

See `assets/query-templates.json`.
