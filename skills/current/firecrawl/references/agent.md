# Firecrawl Agent Reference

Execute autonomous multi-hop research and structured JSON extraction driven by reasoning models (`spark-1-pro`, `spark-1-mini`, `spark-2`).

## Command Syntax

```bash
firecrawl agent "<prompt>" [options]
```

## Options & Flags

- `--urls <urls>`: Comma-separated target URLs to focus research.
- `--model <model>`: Reasoning model:
  - `spark-1-pro`: Default; highest extraction accuracy and reasoning capability.
  - `spark-1-mini`: 60% cheaper than Pro; suitable for simple extractions.
  - `spark-2`: Fastest and cheapest model tier.
- `--schema <json>`: Inline JSON Schema defining expected structured output.
- `--schema-file <path>`: Local file path containing JSON Schema.
- `--max-credits <number>`: Hard cap on credits spent; job fails if exceeded.
- `--wait`: Block until agent run finishes and return structured results.
- `--poll-interval <seconds>`: Polling frequency (default: 5s).
- `--timeout <seconds>`: Maximum wait time in seconds.
- `--status`: Check status of an existing agent job ID.
- `--cancel`: Cancel an active agent job.
- `-o, --output <path>`: Save agent output to disk.
- `--json`: Format output as JSON.

## Recipes

### 1. Multi-URL Competitive Analysis
```bash
firecrawl agent "Compare developer pricing tiers, included API limits, and overage rates" \
  --urls "https://modal.com/pricing,https://replicate.com/pricing,https://runpod.io/pricing" \
  --schema '{"type":"object","properties":{"providers":{"type":"array","items":{"type":"object","properties":{"name":{"type":"string"},"base_price":{"type":"string"},"rate_limits":{"type":"string"}}}}}}' \
  --wait --json --pretty -o .firecrawl/gpu-pricing.json
```

### 2. Autonomous Web Intelligence Gathering
```bash
firecrawl agent "Find the top 5 high-throughput vector databases launched or rewritten in Rust in 2025-2026, their GitHub URLs, and license models" \
  --max-credits 50 \
  --wait --json -o .firecrawl/rust-vector-dbs.json
```

### 3. Background Execution & Polling
```bash
# Start agent without --wait to obtain Job ID
JOB_ID=$(firecrawl agent "Extract complete executive leadership bios" --urls "https://example.com/about" --json | jq -r '.id')

# Check status or cancel if needed
firecrawl agent "$JOB_ID"
firecrawl agent "$JOB_ID" --cancel
```

## Constraints

- Agent tasks take 2 to 5 minutes to complete.
- More credit-intensive than simple `scrape` or `crawl`.
- Always provide `--schema` or `--schema-file` when deterministic JSON shape is required.
