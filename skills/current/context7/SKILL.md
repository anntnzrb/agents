---
name: context7
description: "Use when current library or API documentation must be fetched through Context7 or MCPorter."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Context7

Use Context7 through the configured `context7` MCP server with MCPorter. This skill is read-only: no setup, installs, generated skills, persistent login flows, or configuration mutations.

- MUST resolve `<skill-dir>` dynamically; commands MUST work from any current directory
- MUST invoke MCPorter through `uv run --script <skill-dir>/scripts/cli.py` so the launcher can load Context7 credentials or preserve anonymous access
- The launcher calls managed `mcporter` directly

## Entry points

Primary:

```text
uv run --script <skill-dir>/scripts/cli.py call context7.resolve-library-id --args '{"query":"<user question>","libraryName":"<name>"}'
uv run --script <skill-dir>/scripts/cli.py call context7.query-docs --args '{"libraryId":"<libraryId>","query":"<user question>"}'
```

These recipes encode the complete required inputs. Call them directly; do not list the server or inspect schemas first. If a call reports a missing tool or invalid input, inspect only that tool's live schema, correct the call, and retry once:

```text
uv run --script <skill-dir>/scripts/cli.py list context7.resolve-library-id --schema
uv run --script <skill-dir>/scripts/cli.py list context7.query-docs --schema
```

Optional or unfamiliar inputs also require targeted schema inspection.

## Credentials

- `CONTEXT7_API_KEY` is optional. With it: higher rate limits and custom configuration
- Without it: anonymous access at low rate limits; the launcher strips the auth header from the config automatically
- Keep `.env` beside this skill and populate it from `.env.example`
- Existing `CONTEXT7_API_KEY` values take precedence
- Launcher lookup order:
  - `CONTEXT7_ENV_FILE`
  - skill `.env`
  - `$SKILLS_DIR/context7/.env`
  - nearest ancestor `skills/context7/.env`
- The launcher forwards all arguments to the managed MCPorter command


## Workflow

1. If the user provides a Context7 library ID (`/org/project`, `/org/project/version`, or `/websites/...`), skip resolution
2. Otherwise resolve the library with `context7.resolve-library-id`
3. Pick the best ID by exact name, description relevance, snippet count, source reputation, benchmark score, and requested version
4. Fetch docs with `context7.query-docs`
5. Answer from the fetched docs. If Context7 fails, state the failure and do not silently pretend the answer is current

Keep Context7 retrieval calls to three per user question unless the user explicitly asks for broader exploration. MCPorter diagnostics do not consume that retrieval budget.

## Query discipline

- Use the user's full intent as the query; specific questions rank better than keywords
- Do not send API keys, passwords, personal data, proprietary code, or secrets to Context7

## Required follow-up reads

| Need                                         | Read                      | When                                                                  |
| -------------------------------------------- | ------------------------- | --------------------------------------------------------------------- |
| MCPorter discovery, calls, auth, output, errors | `references/mcporter.md` | Before debugging MCPorter or Context7 behavior |
| Worked docs lookup examples                  | `cookbook/docs-lookup.md` | When choosing IDs, versions, or query wording                         |

## Quick examples

```text
uv run --script <skill-dir>/scripts/cli.py call context7.resolve-library-id --args '{"query":"hooks useState","libraryName":"React"}'
uv run --script <skill-dir>/scripts/cli.py call context7.query-docs --args '{"libraryId":"/reactjs/react.dev","query":"useState hook behavior"}'
```
