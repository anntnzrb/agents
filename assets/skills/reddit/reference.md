# Reddit MCP Reference

## Server setup

- Package: `reddit-mcp-buddy`
- Recommended MCPorter runtime: `bun x reddit-mcp-buddy`
- Recommended server name: `reddit`

Example config entry:

```json
{
  "reddit": {
    "description": "Reddit MCP Buddy",
    "command": "bun",
    "args": ["x", "reddit-mcp-buddy"]
  }
}
```

Notes:

- Upstream docs often show `npx -y reddit-mcp-buddy`.
- In WSL setups that hop into Windows Node, `npx` may fail with UNC/ESM path errors. Prefer `bun` when that appears.

## Tool catalog

### browse_subreddit

Fetch posts from a subreddit sorted by `hot|new|top|rising|controversial`.

Key params: `subreddit` (required), `sort`, `time`, `limit`, `include_nsfw`, `include_subreddit_info`.

### search_reddit

Search posts across all Reddit or selected subreddits.

Key params: `query` (required), `subreddits`, `sort`, `time`, `limit`, `author`, `flair`.

### get_post_details

Fetch one post and comments.

Key params: `url` or `post_id`, `subreddit` (optional but more efficient with `post_id`), `comment_limit`, `comment_sort`, `comment_depth`, `extract_links`, `max_top_comments`.

### user_analysis

Analyze a user profile and activity.

Key params: `username` (required), `posts_limit`, `comments_limit`, `time_range`, `top_subreddits_limit`.

### reddit_explain

Explain Reddit terms and slang.

Key params: `term` (required).

## Environment variables

### Authentication

- `REDDIT_CLIENT_ID`: Reddit app client id
- `REDDIT_CLIENT_SECRET`: Reddit app client secret
- `REDDIT_USERNAME`: Reddit username
- `REDDIT_PASSWORD`: Reddit password
- `REDDIT_USER_AGENT`: optional user agent string

Rate tiers:

- Anonymous: ~10 requests/minute
- App-only (`CLIENT_ID` + `CLIENT_SECRET`): ~60 requests/minute
- Authenticated (all four auth vars): ~100 requests/minute

### Server behavior

- `REDDIT_BUDDY_HTTP`: run HTTP mode instead of stdio (`false` default)
- `REDDIT_BUDDY_PORT`: HTTP port (`3000` default)
- `REDDIT_BUDDY_NO_CACHE`: disable cache (`false` default)

## Operational notes

- Tools are read-only. No posting/moderation actions.
- `get_post_details` should receive `subreddit` with `post_id` when possible to avoid extra lookup calls.

## Troubleshooting

### Bun/MCPorter cache copy error

Symptom:

- `FileNotFound: failed copying files from cache to destination for package ...`

Recovery steps:

1. Retry the same command once (often transient).
2. Warm runtime tools:
   - `bun x mcporter list reddit`
   - `bun x reddit-mcp-buddy --version`
3. Re-run the specific command (`list reddit` or exact `call`) instead of broad `list`.
4. In WSL, run from Linux filesystem paths; avoid UNC/Windows path context where possible.

### WSL + npx startup issue

- If `npx -y reddit-mcp-buddy` fails with UNC/ESM path errors, keep using `bun x reddit-mcp-buddy`.
