# Firecrawl Search Reference

Execute live web, news, image, or categorized searches, optionally scraping full page content in the same request.

## Command Syntax

```bash
firecrawl search "<query>" [options]
```

## Options & Filters

- `--scrape`: Scrape and extract full Markdown content for all top search results.
- `--scrape-formats <formats>`: Formats for scraped results (`markdown`, `html`, `rawHtml`, `links`, etc.). Default: `markdown`.
- `--sources <sources>`: Comma-separated search sources (`web`, `news`, `images`).
- `--categories <categories>`: Filter categories (`github`, `research`, `pdf`). Note: for deep developer PR/issue search or research paper abstracts, use the dedicated developer or research indexes instead.
- `--tbs <value>`: Time-based freshness filter:
  - `qdr:h`: Past hour
  - `qdr:d`: Past 24 hours (day)
  - `qdr:w`: Past week
  - `qdr:m`: Past month
  - `qdr:y`: Past year
- `--location <location>`: Geo-targeting location string (e.g. `Berlin,Germany`).
- `--country <code>`: ISO country code (default: `US`).
- `--limit <number>`: Number of results (default: 5, max: 100).
- `--highlights`: Return query-relevant excerpts (default: enabled).
- `--no-highlights`: Return original full snippet text instead of highlights.
- `-o, --output <path>`: Write results to file.
- `--json`: Force JSON output format.
- `--pretty`: Pretty-print JSON.

## Recipes

### 1. Basic Web Search
```bash
firecrawl search "bun test mocking guide" --json --pretty -o .firecrawl/search-bun.json
```

### 2. Search & Scrape in One Call
```bash
# Fetches top 5 results AND scrapes their full markdown content in one round trip
firecrawl search "zig language async status 2026" --scrape --scrape-formats markdown --json -o .firecrawl/zig-results.json
```

### 3. Recent News Filter
```bash
firecrawl search "anthropic claude release" --sources news --tbs qdr:w --json -o .firecrawl/news.json
```

## Credit Refund Feedback

Every search costs 2 credits. Submitting structured feedback via `firecrawl search-feedback <id>` within 2 minutes refunds 1 credit.

```bash
# Extract search ID and submit feedback in background
if SEARCH_ID=$(jq -er 'select(any(.data[]; length > 0)) | .id' .firecrawl/search-bun.json 2>/dev/null); then
  firecrawl search-feedback "$SEARCH_ID" \
    --rating "good" \
    --valuable-sources '[{"url":"https://bun.sh/docs/cli/test","reason":"Official comprehensive documentation"}]' \
    --missing-content '[{"topic":"Spies","description":"Need clearer examples on spyOn mock resets"}]' \
    --silent &
fi
```

### Feedback Requirements
- Must be sent within 2 minutes of query execution.
- Rating rules:
  - `good`: Requires at least one `--valuable-sources` entry.
  - `partial`: Requires `--valuable-sources` or `--missing-content`.
  - `bad`: Requires `--missing-content` or `--query-suggestions`.
- Daily refund cap is 100 credits per team per UTC day.
- Opt-out toggle: `export FIRECRAWL_NO_SEARCH_FEEDBACK=1`.
