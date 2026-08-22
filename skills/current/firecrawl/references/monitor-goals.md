# Writing Monitor Goals and Queries

Guide for crafting effective `--goal` statements (all monitors) and `--queries` (web monitors) to achieve high precision and low noise.

## Structuring the `--goal`

The goal instructs the server-side LLM judge to differentiate meaningful changes from routine noise. Format goals with 2 to 3 concise sentences:

1. **Trigger Clause**: Start with `Alert when ...` and define the change condition explicitly.
2. **Scope**: Define exact properties, thresholds, entities, or tiers (e.g. `prices, tier names, and storage quotas`).
3. **Intent-Specific Exclusions**: Add an `Ignore ...` clause for user-specific irrelevant changes (e.g. `marketing testimonials`, `page view counters`, `comment counts`).

The judge automatically filters out generic noise (whitespace, timestamps, session IDs, tracking params, and HTML layout shifts), so there is no need to list generic layout tokens in exclusions.

## Goal Formulation Examples

| Goal Intent | Recommended `--goal` |
|---|---|
| Pricing & Plans | `Alert when pricing numbers, tier names, billing frequencies, or included feature quotas change. Ignore marketing copy and customer testimonials.` |
| Job Board / Careers | `Alert when new software engineering or AI research positions are posted or closed. Ignore general company news.` |
| Hacker News Top Stories | `Alert when stories enter, leave, or shift ranking within the top 10. Ignore points, comment counts, and submission timestamps.` |
| API Documentation | `Alert when endpoint paths, request parameters, response schemas, or rate limits change.` |
| Unfiltered Content Shift | `Alert when substantive visible content on this page changes.` |

## Formulating Web Monitor `--queries`

For web monitors, queries govern **recall** (what search finds) and the goal governs **precision** (which hits alert):

- Use **keywords, not conversational sentences**: `PostgreSQL 17 release OR announcement`, not `tell me when postgres 17 comes out`.
- Group synonyms with `OR` and quote multi-word entities (`"Claude 3.7" OR "Claude 4"`).
- Keep each query to 2 to 6 terms.
- Use `--search-window` (`5m`, `15m`, `1h`, `6h`, `24h`, `7d`) to calibrate recency.
- Use `--max-results` (1 to 50, default 10) to cap retrieval volume.

```bash
firecrawl monitor create --name "Compiler Announcements" \
  --schedule "daily at 08:00" \
  --queries "Rust compiler release,LLVM new release announcement" \
  --goal "Alert when a new stable compiler version is released. Ignore nightly builds and third-party blog posts." \
  --search-window 24h --max-results 15 \
  --webhook-url "https://api.example.com/hooks/compiler-alerts"
```
