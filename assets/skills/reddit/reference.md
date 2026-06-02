# Reddit HTTP Reference

## Base URL

- `https://www.reddit.com`
- Use a User-Agent header. Recommended env var: `REDDIT_USER_AGENT`

## Environment

Keep `.env` beside this skill and source it if you want persistent local defaults.

Supported helper lookup order:

- `REDDIT_ENV_FILE`
- `$SKILLS_DIR/reddit/.env`
- nearest ancestor `skills/reddit/.env`

Common vars:

- `REDDIT_USER_AGENT`
- `REDDIT_BASE_URL`

## Public JSON endpoints used by the skill

### Browse subreddit

- `GET /r/<subreddit>/<sort>.json`
- Sorts: `hot`, `new`, `top`, `rising`, `controversial`
- Common params: `limit`, `t`

Example:

```bash
reddit browse technology top time=week limit=10
```

### Search

- `GET /search.json`
- Common params: `q`, `sort`, `t`, `limit`
- The helper can expand legacy args like `subreddits=`, `author=`, and `flair=` into Reddit search syntax.

Example:

```bash
reddit search "llm" subreddits='["programming"]' sort=new time=week limit=10
```

### Post + comments by subreddit/post id

- `GET /r/<subreddit>/comments/<post_id>/.json`
- Common params: `limit`, `sort`, `depth`

Example:

```bash
reddit post programming 1abcde comment_limit=20 comment_sort=top
```

### Post + comments by URL

- Fetch `<reddit-url>.json`
- Same comment params as above

Example:

```bash
reddit post-url "https://reddit.com/r/programming/comments/1abcde/example/" comment_limit=20
```

### User profile + activity

- `GET /user/<username>/about.json`
- `GET /user/<username>/submitted.json`
- `GET /user/<username>/comments.json`

Examples:

```bash
reddit user spez
reddit user-posts spez limit=10
reddit user-comments spez limit=10
reddit user-analysis spez posts_limit=10 comments_limit=10 time_range=month
```

## Rate limits and auth

- Anonymous read-only access works, but throughput is lower.
- Reddit's broader API surface uses OAuth2, but this skill intentionally stays on direct public JSON endpoints.
- If you need private endpoints, write actions, or higher-throughput authenticated access, build that as a separate OAuth-backed mode instead of bolting it onto this helper.

## Glossary helper

`reddit explain <term>` is a local built-in glossary for common Reddit terms like `karma`, `cake day`, `AMA`, `OP`, `TLDR`, and `ELI5`.
