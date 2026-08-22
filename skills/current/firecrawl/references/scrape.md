# Firecrawl Scrape Reference

Extract content from single or multiple URLs into LLM-optimized Markdown, raw HTML, screenshot, or structured JSON.

## Command Syntax

```bash
firecrawl scrape <url...> [options]
# Or direct URL invocation
firecrawl "https://example.com" [options]
```

## Common Flags & Options

- `--only-main-content`: Strip headers, footers, navigation, ads, and sidebars. Recommended for articles and documentation.
- `-H, --html`: Output rendered HTML instead of Markdown.
- `--raw-html`: Output raw unrendered server response HTML.
- `-f, --format <formats>`: Comma-separated list of formats (`markdown`, `html`, `rawHtml`, `links`, `screenshot`, `json`, `images`, `summary`, `changeTracking`, `attributes`, `branding`).
- `--wait-for <ms>`: Milliseconds to wait after page load before scraping (useful for heavy SPAs or delayed hydration).
- `--screenshot`: Capture a viewport screenshot.
- `--full-page-screenshot`: Capture full-length scrollable page screenshot.
- `--schema <json>`: Extract structured JSON conforming to a JSON Schema string.
- `--schema-file <path>`: Extract structured JSON using schema from a local file.
- `--actions <json>`: List of headless browser actions to execute before scraping (`click`, `wait`, `scroll`, `write`, `press`).
- `--actions-file <path>`: JSON file containing list of browser actions.
- `--proxy <mode>`: Proxy routing mode (`auto`, `basic`).
- `--redact-pii`: Redact personally identifiable information from returned text.
- `--include-tags <tags>`: Comma-separated HTML tags or selectors to include.
- `--exclude-tags <tags>`: Comma-separated HTML tags or selectors to exclude.
- `-o, --output <path>`: Output destination file path.
- `--json`: Force JSON output structure.
- `--pretty`: Pretty-print JSON output.
- `--max-age <ms>`: Maximum age of cached content in milliseconds.

## Recipes

### 1. Clean Article Scrape
```bash
firecrawl scrape "https://example.com/post" --only-main-content -o .firecrawl/article.md
```

### 2. Wait for Client-Side Hydration
```bash
firecrawl scrape "https://app.example.com" --wait-for 4000 --only-main-content -o .firecrawl/rendered.md
```

### 3. Pre-Extraction Browser Actions
```bash
firecrawl scrape "https://example.com/data" \
  --actions '[{"type":"click","selector":"button#show-all"},{"type":"wait","milliseconds":2000}]' \
  -o .firecrawl/expanded.md
```

### 4. Structured JSON Extraction via Schema
```bash
firecrawl scrape "https://example.com/pricing" \
  --format json \
  --schema '{"type":"object","properties":{"plans":{"type":"array","items":{"type":"object","properties":{"name":{"type":"string"},"price":{"type":"string"}}}}}}' \
  --pretty -o .firecrawl/pricing.json
```

### 5. Multi-URL Concurrent Scrape
```bash
# Multi-URL mode scrapes concurrently and writes each markdown file under .firecrawl/
firecrawl scrape "https://example.com/page1" "https://example.com/page2" "https://example.com/page3"
```

## Constraints & Anti-Patterns

- When scraping multiple URLs, `-o` is ignored; files are saved automatically under `.firecrawl/` as Markdown.
- If a page requires complex authentication, multi-step navigation, or button clicks that actions cannot cover, scrape first and escalate to `firecrawl interact`.
- Do not use `--query` when you can save the full Markdown and inspect it locally with `grep` or `head`; `--query` adds latency and extra credit cost.
