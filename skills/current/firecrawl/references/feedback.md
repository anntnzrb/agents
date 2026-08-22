# Firecrawl Feedback & Credit Refund Reference

Send structured feedback on search results and scraping jobs to improve upstream models and earn credit refunds.

## Search Feedback (Credit Refund)

Searches cost 2 credits. Submitting structured feedback via `firecrawl search-feedback` within 2 minutes refunds 1 credit.

```bash
# Example guarded pattern
if SEARCH_ID=$(jq -er 'select(any(.data[]; length > 0)) | .id' .firecrawl/search-results.json 2>/dev/null); then
  firecrawl search-feedback "$SEARCH_ID" \
    --rating "good" \
    --valuable-sources '[{"url":"https://example.com/docs","reason":"Clear explanation"}]' \
    --missing-content '[{"topic":"Configuration","description":"Lacked environment variable list"}]' \
    --silent &
fi
```

### Constraints & Rules
- Submit within 2 minutes of query execution.
- Quality rules:
  - `good`: Requires at least one `--valuable-sources` item.
  - `partial`: Requires `--valuable-sources` or `--missing-content`.
  - `bad`: Requires `--missing-content` or `--query-suggestions`.
- Daily refund cap is 100 credits per team per UTC day. When the API reports `dailyCapReached: true`, stop submitting feedback for that day.
- Opt-out toggle: `export FIRECRAWL_NO_SEARCH_FEEDBACK=1`.

## Endpoint Feedback (`/v2/feedback`)

For jobs on other endpoints (`scrape`, `parse`, `map`), submit job feedback with `firecrawl feedback <endpoint> <jobId>`:

```bash
firecrawl feedback scrape "$SCRAPE_JOB_ID" \
  --rating partial \
  --issues missing_markdown \
  --tags docs \
  --note "Code snippets inside tabs were skipped during extraction." \
  --url "https://example.com/docs/install" \
  --silent &
```

### Supported Endpoints
- `search`
- `scrape`
- `parse`
- `map`

### Global Feedback Opt-out
To disable all endpoint feedback reporting across the CLI:
```bash
export FIRECRAWL_NO_ENDPOINT_FEEDBACK=1
```
