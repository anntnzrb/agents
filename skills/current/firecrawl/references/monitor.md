# Firecrawl Monitor Reference

Configure server-side recurring checks on single URLs, URL batches, full crawls, or web searches with LLM semantic change judgment and alerting.

## Target Modes

| Mode | Flags | Target |
|---|---|---|
| Single Page | `--page <url>` | Monitor a specific URL for content diffs |
| URL Batch | `--scrape-urls <url1,url2,...>` | Monitor multiple specific URLs |
| Full Site | `--crawl-url <root-url>` | Monitor all pages discovered during recurring crawls |
| Web Search | `--queries <q1,q2,...> --goal <goal>` | Monitor the entire web for new results matching a goal |

## Command Syntax

```bash
# Create monitor
firecrawl monitor create [options]

# List active monitors
firecrawl monitor list [--limit <number>]

# Get details of a monitor
firecrawl monitor get <monitorId>

# Trigger immediate check run (useful for testing)
firecrawl monitor run <monitorId>

# List checks for a monitor
firecrawl monitor checks <monitorId>

# Inspect a specific check
firecrawl monitor check <monitorId> <checkId> [--page-status changed|new|removed|error|same]

# Pause, resume, or update monitor
firecrawl monitor update <monitorId> --state paused|active

# Delete monitor permanently
firecrawl monitor delete <monitorId>
```

## Options & Flags

- `--name <name>`: Descriptive monitor name.
- `--schedule <text>`: Natural language schedule (e.g. `every 30 minutes`, `hourly`, `daily at 9:00`, `every Monday at 8am`). Minimum interval is 5 minutes.
- `--cron <expression>`: Standard cron expression (e.g. `*/30 * * * *`).
- `--timezone <tz>`: Timezone (default: `UTC`).
- `--goal <text>`: Semantic evaluation goal for change judgment. Required for web queries.
- `--email <emails>`: Comma-separated email recipient addresses.
- `--webhook-url <url>`: Destination URL for alert payloads.
- `--webhook-events <events>`: Comma-separated events (`monitor.page`, `monitor.check.completed`).
- `--retention-days <n>`: Snapshot retention duration for diff generation.
- `--state <state>`: Monitor status (`active`, `paused`).

## Recipes

### 1. Single Page Price & Feature Monitor
```bash
firecrawl monitor create --name "Pricing Monitor" \
  --schedule "every 1 hour" \
  --page "https://example.com/pricing" \
  --goal "Alert when pricing numbers, billing tiers, or plan limits change. Ignore marketing blurbs." \
  --email "alerts@example.com"
```

### 2. Web Monitor for New Releases
```bash
firecrawl monitor create --name "AI Model Releases" \
  --schedule "daily at 09:00" \
  --queries "frontier LLM release,new AI benchmark results" \
  --goal "Alert when a top AI lab publishes a new frontier model or major benchmark leaderboard update." \
  --webhook-url "https://api.example.com/webhooks/firecrawl"
```

### 3. Check Status Inspection
```bash
# Inspect only pages that actually changed during check run
firecrawl monitor check "mon_12345" "chk_67890" --page-status changed --json
```

## Constraints

- Minimum scheduling frequency is 5 minutes.
- External email recipients receive an opt-in confirmation email before alerts begin.
- On HTTP 429 rate limits, pause operations with `firecrawl monitor update <id> --state paused`.
