---
name: reddit
description: "Read Reddit directly via Reddit's public JSON endpoints. Use for subreddit browsing, search, post/comment retrieval, user activity analysis, and common Reddit glossary lookups."
---

# Reddit

Use Reddit directly over HTTP via `reddit.com/*.json`; no mcporter needed.

## Required shell helper

Source the bash helper from this skill once per shell:

```bash
source "${SKILLS_DIR:-skills}/reddit/scripts/reddit.sh"
```

If `SKILLS_DIR` is unavailable, source the same file from your local `skills/` checkout.

Then use `reddit <subcommand>` everywhere below.

Environment check policy: do not stop at `echo $REDDIT_USER_AGENT` in the parent shell. Always run the documented helper entrypoint first; it auto-loads a skill-local `.env` using the lookup order below. Missing `REDDIT_USER_AGENT` is not a hard blocker because this skill has a built-in default.

## Quick start

```bash
reddit browse all hot limit=10
reddit browse technology top time=week limit=10
reddit search "h1b" subreddits='["cscareerquestions","immigration"]' sort=new time=month limit=10
reddit post programming 1abcde comment_limit=20 comment_sort=top
reddit post-url "https://reddit.com/r/programming/comments/1abcde/example/" comment_limit=20
reddit user-analysis spez posts_limit=5 comments_limit=5 time_range=month
reddit explain "cake day"
```

## Environment

- Keep `.env` beside this skill if you want a stable local User-Agent.
- Helper lookup order:
  - `REDDIT_ENV_FILE`
  - `$SKILLS_DIR/reddit/.env`
  - nearest ancestor `skills/reddit/.env`
- Tracked template: `.env.example`
- Common vars:
  - `REDDIT_USER_AGENT`
  - `REDDIT_BASE_URL`

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

```bash
./scripts/test-reddit-http.sh
```

## Reference

See `reference.md`.
