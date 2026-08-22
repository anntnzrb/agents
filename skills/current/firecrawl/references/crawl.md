# Firecrawl Crawl Reference

Extract entire websites or documentation sections recursively, traversing internal links within defined depth and path limits.

## Command Syntax

```bash
firecrawl crawl <url> [options]
```

## Options & Flags

- `--include-paths <paths>`: Comma-separated path prefixes to include (e.g. `/docs,/api`).
- `--exclude-paths <paths>`: Comma-separated path prefixes or regexes to skip (e.g. `/login,/admin`).
- `--limit <number>`: Maximum number of pages to crawl (default: 100).
- `--max-depth <number>`: Maximum link traversal depth.
- `--allow-subdomains`: Crawl subdomains of the target domain.
- `--allow-external-links`: Follow outbound links outside the domain.
- `--crawl-entire-domain`: Crawl whole domain regardless of initial path.
- `--ignore-query-parameters`: Deduplicate URLs that differ only by query parameters.
- `--delay <ms>`: Throttling delay between page requests in milliseconds.
- `--max-concurrency <number>`: Maximum parallel page fetches.
- `--scrape-options <json>`: JSON object with per-page scrape options (e.g. `{"formats":["markdown"],"onlyMainContent":true}`).
- `--scrape-options-file <path>`: File path containing scrape options JSON.
- `--webhook <url-or-json>`: Webhook configuration for crawl events.
- `--wait`: Block until the crawl completes.
- `--progress`: Display a terminal progress indicator while waiting.
- `--poll-interval <seconds>`: Polling interval during wait (default: 5s).
- `--timeout <seconds>`: Overall timeout in seconds.
- `--status`: Check status of an existing crawl job.
- `--cancel`: Cancel an active crawl job.
- `-o, --output <path>`: Write crawl results to file.
- `--json`: Format output as JSON.
- `--pretty`: Pretty-print JSON.

## Recipes

### 1. Synchronous Documentation Crawl
```bash
firecrawl crawl "https://docs.rs/tokio" \
  --include-paths "/tokio" \
  --limit 50 \
  --max-depth 2 \
  --wait --progress \
  --json --pretty -o .firecrawl/tokio-docs.json
```

### 2. Scrape Options with Main Content Only
```bash
firecrawl crawl "https://example.com" \
  --scrape-options '{"formats":["markdown"],"onlyMainContent":true}' \
  --limit 20 --wait -o .firecrawl/site-content.json
```

### 3. Async Background Crawl & Polling
```bash
# 1. Start crawl and capture Job ID
JOB_ID=$(firecrawl crawl "https://example.com" --limit 100 --json | jq -r '.id')

# 2. Check status later
firecrawl crawl "$JOB_ID"

# 3. Wait on job completion
firecrawl crawl "$JOB_ID" --wait --timeout 300 -o .firecrawl/completed-crawl.json
```

## Constraints

- `crawl` consumes 1 API credit per scraped page.
- Always scope with `--include-paths` and `--limit` to prevent runaway crawls across unintended domains.
- Requires authentication (not available on keyless tier).
