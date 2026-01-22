---
name: brave-search
description: Fast, lightweight web search and content extraction via Brave Search. Use for quick lookups, scoping, or lightweight docs/fact checks; optionally pair with exa-search for deep research. Execute Brave MCP calls via MCPorter (load the mcporter skill).
---

# Brave Search MCP

Use Brave Search MCP for web, local, image, video, news, and summarization. This skill documents Brave’s MCP surface; run tool calls with MCPorter.

## Quick start

```bash
mcporter list brave-search
mcporter call brave-search.brave_web_search query="..." count=5 --output json
```

## Common calls

```bash
mcporter call brave-search.brave_web_search query="..." count=5 summary=true --output json
mcporter call brave-search.brave_local_search query="..." count=5 --output json
mcporter call brave-search.brave_news_search query="..." count=5 freshness=pd --output json
mcporter call brave-search.brave_image_search query="..." count=20 --output json
mcporter call brave-search.brave_video_search query="..." count=20 --output json
mcporter call brave-search.brave_summarizer key="..." inline_references=true --output json
```

## Query templates

See `assets/query-templates.json` for reusable parameter templates.

## Reference

See `reference.md` for server setup, tool catalog, and defaults.
