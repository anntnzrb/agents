# Reddit HTTP Reference

## Base URL

- `https://www.reddit.com`
- Use a User-Agent header. Recommended env var: `REDDIT_USER_AGENT`

## Environment

Keep `.env` beside this skill for persistent local defaults; the CLI loads it.

Supported helper lookup order:

- `REDDIT_ENV_FILE`
- `$SKILLS_DIR/reddit/.env`
- nearest ancestor `skills/reddit/.env`

Common vars:

- `REDDIT_USER_AGENT`
- `REDDIT_BASE_URL`

## Output shape (compact default)

`uv run --script <skill-dir>/scripts/cli.py <command> ...` returns compact JSON via `json.dumps(..., separators=(",", ":"))`. Pass `raw=1` to receive the full upstream JSON unchanged.

### Listings (`browse`, `search`, `user-posts`, `user-comments`)

```json
{
  "type": "listing|search|user-posts|user-comments",
  "subreddit|user|query": "...",
  "sort": "hot",
  "time": "all",
  "count": 10,
  "results": [
    {
      "id": "abc",
      "title": "...",
      "subreddit": "...",
      "author": "...",
      "score": 123,
      "num_comments": 12,
      "url": "https://...",
      "permalink": "/r/.../comments/.../...",
      "created_utc": 1718600000.0,
      "flair": "Discussion",
      "selftext_preview": "First 240 chars of selftext…",
      "over_18": false,
      "is_self": true
    }
  ]
}
```

Fields `flair` and `selftext_preview` are omitted when empty. `selftext` is collapsed to single spaces and truncated to 240 chars. Authors `[deleted]` become `null`.

### Post + comments (`post`, `post-url`)

```json
{
  "type": "post",
  "post": { "...compact listing fields..." },
  "comments": [
    {
      "id": "...",
      "author": "...",
      "score": 12,
      "body": "Comment body, whitespace collapsed.",
      "created_utc": 1718600000.0,
      "permalink": "/r/.../comments/.../.../...",
      "depth": 0
    }
  ]
}
```

`more` placeholder comments are skipped. `depth` is `0` for top-level comments and increments for each reply level.

### User (`user`)

```json
{
  "type": "user",
  "user": "spez",
  "profile": {
    "name": "spez",
    "created_utc": 1132755200.0,
    "link_karma": 12345,
    "comment_karma": 67890,
    "total_karma": 80235,
    "verified": false,
    "is_gold": false,
    "is_mod": true
  }
}
```

### `user-analysis` (always structured)

```json
{
  "type": "user-analysis",
  "user": "spez",
  "time_range": "month",
  "profile": { "...as above..." },
  "posts": [ { "...compact listing fields..." } ],
  "comments": [
    {
      "id": "...",
      "subreddit": "...",
      "author": "...",
      "score": 12,
      "body_preview": "First 240 chars of comment body…",
      "permalink": "/r/.../comments/.../.../...",
      "created_utc": 1718600000.0
    }
  ],
  "top_subreddits": [ { "subreddit": "announcements", "count": 42 } ]
}
```

### `explain` (always structured)

```json
{ "term": "cake day", "definition": "The anniversary of a Reddit account creation date, shown with a cake icon." }
```

The term is normalized before lookup: trim, collapse internal whitespace, lowercase, and treat `-` as space. Empty / whitespace-only input is a usage error (rc=2).

## Errors

HTTP and parse failures emit one-line compact JSON on stderr:

```json
{
  "error": {
    "provider": "reddit",
    "status": 403,
    "message": "Reddit returned HTTP 403",
    "body_bytes": 1234,
    "body_preview": "blocked by network security...",
    "body_truncated": true,
    "kind": "network_security_block"
  }
}
```

- `provider` is always `"reddit"`.
- `status` is the HTTP status from Reddit, or `null` for transport-level errors.
- `body_bytes` is the upstream body size.
- `body_preview` is the first 500 chars of the body, decoded UTF-8.
- `body_truncated` is `true` when the body is longer than 500 chars.
- `kind` is `"network_security_block"` when the body text contains `blocked by network security` (case-insensitive), `"network_error"` for `URLError`, `"invalid_json"` for unparseable bodies, and is omitted otherwise.

HTTP errors exit with `22`. Network errors exit with `1`. Validation / usage errors exit with `2` and a concise stderr line (no traceback).

## Public JSON endpoints used by the skill

### Browse subreddit

- `GET /r/<subreddit>/<sort>.json`
- Sorts: `hot`, `new`, `top`, `rising`, `controversial`
- Common params: `limit`, `t`
- The sort positional arg must appear before any `key=value`; a stray positional token after `key=value` is a usage error.

Example:

```bash
reddit browse technology top time=week limit=10
```

### Search

- `GET /search.json`
- Common params: `q`, `sort`, `t`, `limit`
- The helper expands legacy args `subreddits=`, `author=`, `flair=` into Reddit search syntax.
- `subreddits=` must parse as a JSON list of non-empty strings.

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
- URL must use `http://` or `https://`; otherwise rc=2.
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

`user-analysis` validates: `posts_limit`, `comments_limit`, `top_subreddits_limit` must be non-negative integers; `time_range` must be `day|week|month|year|all`. Invalid values return rc=2 with no silent fallback.

## `raw=1` passthrough

Append `raw=1` anywhere in the args to receive the upstream JSON unchanged (no compact envelope, no stderr rewrite). Works with `browse`, `search`, `post`, `post-url`, `user`, `user-posts`, `user-comments`. `explain` and `user-analysis` are always structured.

```bash
reddit browse all hot limit=25 raw=1
reddit search "llm" raw=1
```

## Rate limits and auth

- Anonymous read-only access works, but throughput is lower.
- Reddit's broader API surface uses OAuth2, but this skill intentionally stays on direct public JSON endpoints.
- If you need private endpoints, write actions, or higher-throughput authenticated access, build that as a separate OAuth-backed mode instead of bolting it onto this helper.

## Glossary helper

`reddit explain <term>` is a local built-in glossary for common Reddit terms like `karma`, `cake day`, `AMA`, `OP`, `TLDR`, and `ELI5`. Term normalization trims whitespace, lower-cases, collapses internal runs of whitespace, and treats `-` as space (so `Cake-Day`, `cake  day`, and `cake day` all resolve to the same entry).
