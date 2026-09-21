---
disable-model-invocation: true
name: firecrawl
description: "Use when scraping, crawling, mapping, searching the web, or extracting structured data via Firecrawl."
license: AGPL-3.0-or-later
compatibility: Requires Firecrawl MCP server via MCPorter.
---

# Firecrawl

Web scraping, crawling, mapping, and structured data extraction via the dynamic MCP runner (`mcporter call firecrawl.<tool>`).

Tool schemas are dynamic and authoritative. When discovering capabilities or parameter requirements, inspect the live server directly.

## Discovery Workflow for Agents (Cold Start)

1. **Roster of available tools (Short listing):**
   ```sh
   mcporter list firecrawl --brief
   ```
2. **Inspect exact parameters and schema for a specific tool:**
   ```sh
   mcporter list firecrawl.<tool_name> --schema
   ```

## Common Operations

### 1. Scrape a URL (Markdown / Clean Content)
```sh
mcporter call firecrawl.scrape --args '{"url": "https://example.com", "formats": ["markdown"]}' --output json
```

### 2. Crawl a Website (Recursive Multi-Page)
```sh
mcporter call firecrawl.crawl --args '{"url": "https://docs.example.com", "limit": 20, "maxDepth": 2}' --output json
```

### 3. Map Sitemaps and URLs
```sh
mcporter call firecrawl.map --args '{"url": "https://example.com", "search": "pricing"}' --output json
```

### 4. Structured Data Extraction (JSON Schema)
```sh
mcporter call firecrawl.extract --args '{"urls": ["https://example.com/product/123"], "schema": {"type": "object", "properties": {"name": {"type": "string"}, "price": {"type": "number"}}}}' --output json
```

## Execution Rules & Safety
- **Dynamic Schema Inspection:** Run `mcporter list firecrawl.<tool> --schema` when parameters or required arguments are uncertain.
- **Large payloads:** Route structured results to local files using `--output-file <path>` or inspect JSON directly.
