---
name: firecrawl
description: "Use when scraping, crawling, mapping, searching the web, extracting structured data, or monitoring diffs via Firecrawl."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Firecrawl CLI

Search, scrape, crawl, map, interact with, and monitor the live web. Returns clean, LLM-optimized Markdown and structured JSON.

## Command Runner

Run via installed `firecrawl` binary or ephemeral `bun x firecrawl-cli@latest`. Do not invoke `npx`, `npm`, or raw `node`.

```bash
# Verify status, concurrency limit, and remaining API credits
firecrawl --status
# Or ephemeral
bun x firecrawl-cli@latest --status
```

## Escalation Workflow

Select the narrowest command fitting the task:

1. **Search**: No URL known yet. Find pages, discover sources, query developer/paper indexes.
2. **Scrape**: Specific URL known. Extract clean Markdown or structured JSON. Static or JS-rendered.
3. **Map + Scrape**: Target site known, exact path unknown. Use `map --search` to find URLs, then scrape.
4. **Crawl**: Bulk content extraction across an entire domain or documentation section.
5. **Interact**: Post-scrape browser actions (clicks, form fills, auth, pagination, infinite scroll).
6. **Agent**: Multi-hop autonomous extraction into structured JSON schemas across complex sites.
7. **Monitor**: Recurring checks, diffs, and change alerting (email or webhook) instead of manual loops.

## Quick Start

```bash
# Clean markdown scrape (main article only)
firecrawl scrape "https://example.com" --only-main-content -o .firecrawl/page.md

# Web search with direct page scraping
firecrawl search "query terms" --scrape -o .firecrawl/search.json --json

# Map endpoints matching a path
firecrawl map "https://docs.example.com" --search "auth" -o .firecrawl/urls.txt

# Recursive docs crawl with depth limit
firecrawl crawl "https://docs.example.com" --include-paths "/docs" --limit 50 --wait -o .firecrawl/crawl.json

# Live page interaction after scrape
firecrawl scrape "https://example.com/login"
firecrawl interact "Fill in email with user@example.com and submit"
firecrawl interact stop
```

## Required Follow-up Reads

| Need | Read | When |
|---|---|---|
| Page scraping & extraction | `references/scrape.md` | Scraping URLs, JS hydration, schemas, screenshots, or actions |
| Web & news search | `references/search.md` | Searching the live web, time filters, sources, or credit refunds |
| Developer & bug index | `references/developer-index.md` | Searching issues, merged PRs, READMEs, and developer docs |
| Research paper corpus | `references/research-index.md` | PubMed, bioRxiv, medRxiv, arXiv paper search and citation graphs |
| Bulk site crawling | `references/crawl.md` | Multi-page domain extraction, path regexes, depth, concurrency |
| URL & sitemap mapping | `references/map.md` | Discovering site routes and subdomains before scraping |
| Autonomous AI extraction | `references/agent.md` | Complex multi-page schema extraction using reasoning models |
| Browser session driving | `references/interact.md` | Clicks, forms, session profiles, Playwright/Node/Bash code |
| Change detection & alerts | `references/monitor.md` | Setting up recurring checks, schedules, diffs, and webhooks |
| Monitor goal authoring | `references/monitor-goals.md` | Tuning `--goal` precision and `--queries` recall for monitors |
| Structured field diffs | `references/monitor-json-tracking.md` | Per-field JSON change tracking and schema extraction diffs |
| Local document parsing | `references/parse.md` | Converting local PDF, DOCX, XLSX, or HTML files to Markdown |
| Bulk site download | `references/download.md` | Mirroring site hierarchy to local markdown and assets |
| Job feedback & refunds | `references/feedback.md` | Submitting feedback to refund credits and tune search |
| Setup, auth & security | `references/install-and-security.md` | API keys, self-hosted endpoints, prompt injection guards |

## Output & Storage Rules

- Always route outputs to `.firecrawl/` using `-o` to avoid flooding agent context.
- Always quote URLs in shell commands to prevent `&` and `?` parameter splitting.
- Inspect fetched files with bounded tools (`head`, `grep`, `jq`, or range reads).
- Single format flag outputs raw text; multiple formats (`--format markdown,links`) output JSON.

## Environment & Keyless Fallback

- Set `FIRECRAWL_API_KEY` for full cloud access, higher rate limits, and crawl/map/agent features.
- Connect to self-hosted instances with `export FIRECRAWL_API_URL="http://localhost:3002"` (no key required).
- Keyless free tier supports `scrape`, `search`, and `interact` with per-IP rate limits.
