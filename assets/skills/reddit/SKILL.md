---
name: reddit
description: "Read Reddit directly via Reddit's public JSON endpoints. Use for subreddit browsing, search, post/comment retrieval, user activity analysis, and common Reddit glossary lookups."
---

# Reddit

Use Reddit directly over HTTP via `reddit.com/*.json` through the bundled cross-platform Python CLI.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

Environment check policy: run the documented CLI entrypoint first; it auto-loads a skill-local `.env` using the lookup order below. Missing `REDDIT_USER_AGENT` is not a hard blocker because this skill has a built-in default.

## Quick start

```text
uv run --script <skill-dir>/scripts/cli.py browse all hot limit=10
uv run --script <skill-dir>/scripts/cli.py browse technology top time=week limit=10
uv run --script <skill-dir>/scripts/cli.py search "h1b" subreddits='["cscareerquestions","immigration"]' sort=new time=month limit=10
uv run --script <skill-dir>/scripts/cli.py post programming 1abcde comment_limit=20 comment_sort=top
uv run --script <skill-dir>/scripts/cli.py post-url "https://reddit.com/r/programming/comments/1abcde/example/" comment_limit=20
uv run --script <skill-dir>/scripts/cli.py user-analysis spez posts_limit=5 comments_limit=5 time_range=month
uv run --script <skill-dir>/scripts/cli.py explain "cake day"
```

## Environment

- Keep `.env` beside this skill if you want a stable local User-Agent.
- CLI lookup order:
  - `REDDIT_ENV_FILE`
  - skill `.env`
  - `$SKILLS_DIR/reddit/.env`
  - nearest ancestor `skills/reddit/.env`
- Tracked template: `.env.example`
- Common vars:
  - `REDDIT_USER_AGENT`
  - `REDDIT_BASE_URL`

## Failure handling

- Do not treat the parent shell as the source of truth for `REDDIT_USER_AGENT`; always run the CLI so it can load its own `.env`.
- If env loading still fails, set `REDDIT_ENV_FILE` dynamically from the skill path rather than hard-coding a machine-specific directory.
- Missing `REDDIT_USER_AGENT` after CLI lookup is not a hard blocker because the CLI has a built-in default.
- Distinguish env lookup behavior from HTTP failures or Reddit-side blocking; report the actual request failure instead of claiming the skill lacks credentials.

## Notes

- Public JSON endpoints work anonymously for basic read-only use.
- Set a custom `REDDIT_USER_AGENT` for better hygiene and fewer blocks.
- Reddit also has OAuth-backed APIs, but this skill intentionally stays on public JSON endpoints for low-friction read-only access.
- If you need authenticated/private/high-throughput access later, treat that as a separate OAuth feature instead of overloading this helper.
- `search` accepts legacy convenience args:
  - `subreddits='["a","b"]'`
  - `author=<username>`
  - `flair=<text>`
- `post` / `post-url` accept legacy aliases:
  - `comment_limit=` -> `limit=`
  - `comment_sort=` -> `sort=`
  - `comment_depth=` -> `depth=`

## Query templates

See `assets/query-templates.json`.

## Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```

## Reference

See `reference.md`.
