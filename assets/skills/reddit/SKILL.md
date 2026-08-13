---
name: reddit
description: Browse, search, and retrieve Reddit posts, comments, subreddits, and user activity via JSON.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb

---

# Reddit

Use public `reddit.com/*.json` over HTTP via the bundled cross-platform Python CLI.

## Entry point

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

`<skill-dir>` = this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch. Always run this documented entrypoint first: it auto-loads a skill-local `.env` using the lookup order below. Missing `REDDIT_USER_AGENT` is non-blocking because the CLI has a built-in default.

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

## Output

Default HTTP commands return compact agent-shaped JSON:
- `browse` / `search` / `user-posts` / `user-comments`: `{"type": ..., "<subreddit|user|query>": ..., "sort": ..., "time": ..., "count": N, "results": [...]}`. Each result retains `id`, `title`, `subreddit`, `author`, `score`, `num_comments`, `url`, `permalink`, `created_utc`, `over_18`, and `is_self`; `flair` and `selftext_preview` appear when set, with the latter collapsed and capped.
- `post` / `post-url`: `{"type": "post", "post": {...compact listing fields...}, "comments": [{"id", "author", "score", "body", "created_utc", "permalink", "depth"}, ...]}`. Drop `more` placeholders; collapse comment bodies to single-spaced text.
- `user`: `{"type": "user", "user": "...", "profile": {"name", "created_utc", "link_karma", "comment_karma", "total_karma", "verified", "is_gold", "is_mod"}}`
- `user-analysis`: structured summary; see `reference.md`.
- `explain`: `{"term": "<normalized>", "definition": "..."}`.

`raw=1` returns full upstream JSON unchanged for `browse`, `search`, `post`, `post-url`, `user`, `user-posts`, and `user-comments`; `explain` and `user-analysis` always remain structured.

## Errors

HTTP failures emit this one-line compact JSON to stderr:

```json
{"error":{"provider":"reddit","status":403,"message":"Reddit returned HTTP 403","body_bytes":1234,"body_preview":"...","body_truncated":true,"kind":"network_security_block"}}
```

Fields: `error.provider` = `"reddit"`; `error.status` = Reddit HTTP status, or `null` for network errors; `error.message` = short human-readable cause; `error.body_bytes` = upstream size; `error.body_preview` = first 500 upstream chars, UTF-8 decoded; `error.body_truncated` = `true` when body exceeds preview cap. `error.kind`: `"network_security_block"` when body contains `blocked by network security`; `"network_error"` for `URLError`; `"invalid_json"` for unparseable responses; otherwise omitted.

Exit codes: HTTP `22`; network `1`; validation `2` with concise stderr and no traceback.

## Environment

- Keep `.env` beside this skill for a stable local User-Agent.
- Lookup order: `REDDIT_ENV_FILE` → skill `.env` → `$SKILLS_DIR/reddit/.env` → nearest ancestor `skills/reddit/.env`.
- Tracked template: `.env.example`.
- Common vars: `REDDIT_USER_AGENT`, `REDDIT_BASE_URL`.

## Failure handling

- Never treat the parent shell as `REDDIT_USER_AGENT` source of truth; run the CLI so it loads its own `.env`.
- If loading still fails, set `REDDIT_ENV_FILE` dynamically from the skill path; never hard-code a machine-specific directory.
- Missing `REDDIT_USER_AGENT` after lookup is non-blocking because of the built-in default.
- Distinguish env lookup, HTTP failure, and Reddit blocking; report the actual request failure, not missing credentials.
- `network_security_block` means Reddit or an upstream proxy refused the request, not local configuration failure; switch `REDDIT_USER_AGENT` or egress before retrying.

## Aliases

- `search`: `subreddits='["a","b"]'` must be a JSON list of non-empty strings; malformed values return rc=2. Also accepts `author=<username>`, `flair=<text>`, and `time=` as alias for `t=`.
- `post` / `post-url`: `comment_limit=` → `limit=`, `comment_sort=` → `sort=`, `comment_depth=` → `depth=`.

## Validation

- `browse` requires a subreddit. Sort must be `hot|new|top|rising|controversial` and precede every `key=value` arg; stray positional tokens after `key=value` return rc=2.
- `post-url` requires an `http://` or `https://` URL; otherwise rc=2.
- `user-analysis` numeric args must be non-negative integers; `time_range` must be `day|week|month|year|all`. Invalid values return rc=2; never silently fall back to `all`.
- `explain` lower-cases and trims input; hyphens become spaces for glossary lookup; empty/whitespace-only input returns rc=2.

## Required reads

|Need|Read|When|
|---|---|---|
|Pick command and args for a Reddit query|`reference.md` (Endpoints)|Before invoking a new command|
|Reuse a known query shape|`assets/query-templates.json`|When request matches a known template|
|Understand compact JSON or error shape|`reference.md` (Output shape / Errors)|When consuming structured output or stderr|
|Diagnose `network_security_block`|`SKILL.md` (Failure handling)|When `error.kind` is `network_security_block`|
|Override User-Agent / base URL|`.env.example`|When changing HTTP identity or using a mirror|
|Future refactor expectations and regression traps|`references/future-refactor.md`|When planning a larger refactor or changing output/error contracts|

## Notes

Public JSON endpoints support anonymous basic read-only use. Set a custom `REDDIT_USER_AGENT` for hygiene and fewer blocks. OAuth-backed APIs exist but this skill intentionally uses public JSON for low-friction read-only access. Authenticated, private, or high-throughput access belongs in a separate OAuth feature, not this helper.

Query templates: `assets/query-templates.json`.

## Validation command

```text
uv run --script <skill-dir>/scripts/cli.py --help
```

Reference: `reference.md`.
