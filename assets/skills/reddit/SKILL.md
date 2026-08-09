---
name: reddit
description: Browse, search, and retrieve Reddit posts, comments, subreddits, and user activity via JSON.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

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
uv run --script <skill-dir>/scripts/cli.py browse all hot limit=25 raw=1
```

## Output shape

By default HTTP commands return a compact agent-shaped JSON envelope. The shape varies per command:

- `browse` / `search` / `user-posts` / `user-comments`:
  `{"type": ..., "<subreddit|user|query>": ..., "sort": ..., "time": ..., "count": N, "results": [...]}`.
  Each result keeps: `id`, `title`, `subreddit`, `author`, `score`, `num_comments`, `url`, `permalink`, `created_utc`, `flair` (when set), `selftext_preview` (when set, collapsed and capped), `over_18`, `is_self`.
- `post` / `post-url`:
  `{"type": "post", "post": {...compact listing fields...}, "comments": [{"id", "author", "score", "body", "created_utc", "permalink", "depth"}, ...]}`.
  `more` placeholder comments are dropped. Comment bodies are collapsed to single-spaced text.
- `user`: `{"type": "user", "user": "...", "profile": {"name", "created_utc", "link_karma", "comment_karma", "total_karma", "verified", "is_gold", "is_mod"}}`
- `user-analysis`: structured summary, see `reference.md`
- `explain`: `{"term": "<normalized>", "definition": "..."}`

Pass `raw=1` to receive the full upstream JSON unchanged. `raw=1` works with `browse`, `search`, `post`, `post-url`, `user`, `user-posts`, `user-comments`. `explain` and `user-analysis` are always structured.

## Errors

HTTP failures emit one-line compact JSON to stderr:

```json
{"error":{"provider":"reddit","status":403,"message":"Reddit returned HTTP 403","body_bytes":1234,"body_preview":"...","body_truncated":true,"kind":"network_security_block"}}
```

Fields:

- `error.provider` — `"reddit"`
- `error.status` — HTTP status from Reddit (or `null` for network errors)
- `error.message` — short human-readable cause
- `error.body_bytes` — upstream response size
- `error.body_preview` — first 500 chars of the upstream body, decoded UTF-8
- `error.body_truncated` — `true` if the body was longer than the preview cap
- `error.kind` — `"network_security_block"` when the body text contains `blocked by network security`; `"network_error"` for `URLError`; `"invalid_json"` for unparseable responses; omitted otherwise

HTTP errors return exit code `22`. Network errors return `1`. Validation errors return `2` with a concise stderr line, no traceback.

## Environment

- Keep `.env` beside this skill if you want a stable local User-Agent
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

- Do not treat the parent shell as the source of truth for `REDDIT_USER_AGENT`; always run the CLI so it can load its own `.env`
- If env loading still fails, set `REDDIT_ENV_FILE` dynamically from the skill path rather than hard-coding a machine-specific directory
- Missing `REDDIT_USER_AGENT` after CLI lookup is not a hard blocker because the CLI has a built-in default
- Distinguish env lookup behavior from HTTP failures or Reddit-side blocking; report the actual request failure instead of claiming the skill lacks credentials
- A `network_security_block` error means Reddit (or an upstream proxy) refused the request, not a local config issue. Switch `REDDIT_USER_AGENT` or change egress before retrying

## Aliases

- `search` accepts:
  - `subreddits='["a","b"]'` (must be a JSON list of non-empty strings; malformed values return rc=2)
  - `author=<username>`
  - `flair=<text>`
  - `time=` is an alias for `t=`
- `post` / `post-url` accept:
  - `comment_limit=` → `limit=`
  - `comment_sort=` → `sort=`
  - `comment_depth=` → `depth=`

## Validation rules

- `browse` requires a subreddit; sort must be `hot|new|top|rising|controversial` and appear before any `key=value` arg. A stray positional token after `key=value` is rc=2
- `post-url` requires an `http://` or `https://` URL. Anything else is rc=2
- `user-analysis` numeric args must be non-negative integers; `time_range` must be `day|week|month|year|all`. Invalid values return rc=2 (no silent "all" fallback)
- `explain` lower-cases and trims whitespace; hyphens are treated as spaces for glossary lookup. Empty / whitespace-only input is rc=2

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Pick the right command and args for a Reddit query | `reference.md` (Endpoints) | Before invoking a new command |
| Reuse a known query shape | `assets/query-templates.json` | When the request matches a known template |
| Understand the compact JSON envelope or error shape | `reference.md` (Output shape / Errors) | When consuming structured output or stderr |
| Diagnose a `network_security_block` | `SKILL.md` (Failure handling) | When `error.kind` is `network_security_block` |
| Override User-Agent / base URL | `.env.example` | When changing HTTP identity or hitting a mirror |
| Future refactor concerns, expectations, and regression traps | `references/future-refactor.md` | You are planning a larger refactor or changing output/error contracts |

## Notes

- Public JSON endpoints work anonymously for basic read-only use
- Set a custom `REDDIT_USER_AGENT` for better hygiene and fewer blocks
- Reddit also has OAuth-backed APIs, but this skill intentionally stays on public JSON endpoints for low-friction read-only access
- If you need authenticated/private/high-throughput access later, treat that as a separate OAuth feature instead of overloading this helper

## Query templates

See `assets/query-templates.json`.

## Validation

```text
uv run --script <skill-dir>/scripts/cli.py --help
```

## Reference

See `reference.md`.
