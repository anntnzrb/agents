---
name: context7
description: Retrieve up-to-date library/API docs and code examples via the Context7 HTTP API. Use for library-specific questions, setup/config steps, code generation, and verifying current APIs.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
disable-model-invocation: true
---

# Context7

Use Context7 for version-specific docs and code examples through the bundled cross-platform Python CLI.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

Credential check policy: run the documented CLI entrypoint first; it auto-loads a skill-local `.env` using the lookup order below. The API key is optional for basic usage, so only report a credential problem if the real command still fails or the user specifically needs higher-rate access.

## Workflow

1. If you do not know the library ID, search first.
2. Inspect the top matches by `title`, `description`, and `totalSnippets`.
3. Fetch docs with `docs <library-id> <query>`.
4. Use `json ...` only when structured parsing is needed.

## Quick start

```text
uv run --script <skill-dir>/scripts/cli.py search react "hooks useState"
uv run --script <skill-dir>/scripts/cli.py id react "hooks useState"
uv run --script <skill-dir>/scripts/cli.py docs /vercel/next.js "app router server actions"
uv run --script <skill-dir>/scripts/cli.py json /fastapi/fastapi "dependency injection"
```

## Credentials

- API key is optional but recommended for higher rate limits.
- Keep `.env` beside this skill.
- CLI lookup order:
  - `CONTEXT7_ENV_FILE`
  - skill `.env`
  - `$SKILLS_DIR/context7/.env`
  - nearest ancestor `skills/context7/.env`
- Tracked template: `.env.example`
- Header used when present: `Authorization: Bearer <key>`

## Failure handling

- Do not treat the parent shell as the source of truth for `CONTEXT7_API_KEY`; always run the CLI so it can load its own `.env`.
- If env loading still fails, set `CONTEXT7_ENV_FILE` dynamically from the skill path rather than hard-coding a machine-specific directory.
- Distinguish env behavior from API failures:
  - missing key after CLI lookup usually means env discovery failed, but a key is optional for public low-rate usage
  - HTTP `401`, `404`, `422`, `429`, or `503` means the request reached Context7 and failed for auth/library/rate/service reasons
- Report the actual HTTP failure mode instead of collapsing everything into “missing credentials”.

## Notes

- If you already know the library ID (`/org/project`, `/org/project/version`, or `/websites/...`), skip search.
- `docs` and `json` accept library IDs with or without a leading `/`; examples keep the canonical slash form.
- Prefer exact title/source matches; use higher `totalSnippets` as a tiebreaker, not the only signal.
- `docs` uses `type=txt` because it is easier to read in agent output.
- Public endpoint works without an API key for basic usage; expect lower rate limits.
- Override `CONTEXT7_BASE_URL` if you need to point at a different host.

## Common examples

```text
uv run --script <skill-dir>/scripts/cli.py id react "hooks useState"
uv run --script <skill-dir>/scripts/cli.py docs /websites/react_dev "useState"
uv run --script <skill-dir>/scripts/cli.py id nextjs "routing app router"
uv run --script <skill-dir>/scripts/cli.py docs /vercel/next.js "app router"
uv run --script <skill-dir>/scripts/cli.py id fastapi "dependencies dependency injection"
uv run --script <skill-dir>/scripts/cli.py docs /fastapi/fastapi "dependency injection"
```

## Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```

## Query templates

See `assets/query-templates.json`.
