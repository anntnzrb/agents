---
name: firecrawl
description: "Use when scraping, crawling, mapping, searching the web, or extracting structured data via Firecrawl."
license: AGPL-3.0-or-later
compatibility: Requires Firecrawl MCP server via MCPorter.
---

# Firecrawl

Web scraping, crawling, mapping, search, and structured data extraction through the Firecrawl MCP server, called with `mcporter call firecrawl.<tool>`.

The live server is the authority for tool names and schemas. Every tool name carries the `firecrawl_` prefix: call `firecrawl.firecrawl_scrape`, not `firecrawl.scrape`.

## Discover tools

1. List the tools with compact signatures:
   ```sh
   mcporter list firecrawl --brief
   ```
2. Before a call with uncertain arguments, read the full schemas. The output is large (about 100 KB for the whole server), so search it for the tool you need:
   ```sh
   mcporter list firecrawl --schema
   ```

## Common calls

Scrape one page as Markdown:
```sh
mcporter call firecrawl.firecrawl_scrape --args '{"url": "https://example.com", "formats": ["markdown"], "onlyMainContent": true}' --output json
```

Extract structured data from a known page. Pass the schema in `jsonOptions`:
```sh
mcporter call firecrawl.firecrawl_scrape --args '{"url": "https://example.com/pricing", "formats": ["json"], "jsonOptions": {"schema": {"type": "object", "properties": {"plan": {"type": "string"}, "price": {"type": "number"}}}}}' --output json
```

List a site's URLs without fetching them:
```sh
mcporter call firecrawl.firecrawl_map --args '{"url": "https://docs.example.com", "search": "pricing", "limit": 50}' --output json
```

Crawl several pages. The call polls until the crawl finishes and can return a large result:
```sh
mcporter call firecrawl.firecrawl_crawl --args '{"url": "https://docs.example.com", "includePaths": ["/docs/.*"], "limit": 20, "maxDiscoveryDepth": 2}' --output json
```

Search the web:
```sh
mcporter call firecrawl.firecrawl_search --args '{"query": "firecrawl mcp release notes", "limit": 5}' --output json
```

## Rules

- Save large results with shell redirection: append `> <temp-dir>/page.json` to the call. `mcporter call` has no `--output-file` flag.
- `firecrawl_extract` is a deprecated compatibility tool. Use `firecrawl_scrape` with `formats: ["json"]` for known URLs, and `firecrawl_agent` when the URLs are unknown or the data spans several sites.
- Set `maxAge: 0` on `firecrawl_scrape` when the page must be fetched live. Firecrawl can otherwise serve recently indexed content.
