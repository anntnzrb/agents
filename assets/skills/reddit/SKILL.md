---
name: reddit
description: "Reddit MCP via reddit-mcp-buddy for browsing subreddit posts, searching Reddit, fetching post details and comments, analyzing users, and explaining Reddit terms. Use when tasks involve Reddit trend discovery, discussion lookup, post/comment retrieval, user activity analysis, or Reddit jargon lookup. Load the mcporter skill to execute this skill's MCP calls."
---

# Reddit MCP

Use Reddit MCP Buddy for read-only Reddit browsing and analysis.

## Notes

- MCPorter server name: `reddit`
- Auth is optional; anonymous mode works without credentials
- Rate limit tiers: anonymous (~10 req/min), app-only (~60 req/min), authenticated (~100 req/min)
- Anonymous mode is low-throughput; keep `limit` around 5-25 for multi-call workflows
- For broad investigations, pace calls or set auth env vars to avoid rate-limit failures
- For `get_post_details`, prefer `post_id` + `subreddit` when known to reduce API calls

## Quick start

```bash
browse_subreddit subreddit="all" sort="hot" limit=10
search_reddit query="<topic>" sort="relevance" limit=10
```

## Common calls

```bash
browse_subreddit subreddit="technology" sort="top" time="week" limit=25
search_reddit query="h1b layoffs" subreddits='["cscareerquestions","immigration"]' sort="new" time="month" limit=25
get_post_details url="https://reddit.com/r/<subreddit>/comments/<post_id>/"
get_post_details post_id="<post_id>" subreddit="<subreddit>" comment_limit=50 comment_sort="top"
user_analysis username="<username>" posts_limit=10 comments_limit=10 time_range="month"
reddit_explain term="cake day"
```

## Query templates

See `assets/query-templates.json` for reusable parameter templates.

## Reference

See `reference.md` for server setup, tool catalog, and environment variables.

## Validation

Run the local regression suite:

```bash
sh scripts/test-reddit-mcporter.sh
```
