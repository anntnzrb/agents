---
name: web-ops
description: Unified web router for external reading, deep scraping escalation, and live web search
condition:
  - 'https?://[^\s"''`)]+'
  - '\b(?:web\s+search|search\s+the\s+web|look\s+up|google|bing|firecrawl|scrape|crawl|sitemap|browser\s+action)\b'
scope:
  - text
  - thinking
  - tool:bash
interruptMode: never
---
# Web Operations & Routing Policy

Route external web queries through the narrowest and most efficient tool/skill:

---

### 1. Web Search & Intelligence (`omp-search` skill)
When the user asks to search the web, query live internet information, find recent releases, or look up facts:
- **MUST** use the `omp-search` CLI wrapper via `bash`:
  ```bash
  omp-search "<query>" [--recency day|week|month|year] [--limit <N>]
  # Or explicit provider selection
  omp-search "<query>" --providers exa,parallel
  ```
- Emits structured JSON (`ok`, `answer`, `sources`, `providers`) with deduplicated and synthesized intelligence across configured providers.

---

### 2. Standard Web Reading (Built-in `read` tool)
When an explicit link or target URL is provided (`http://` or `https://`):
- **Always try the built-in `read` tool first**.
- Fast, runs in-process with zero subshell overhead, and includes native scrapers for `docs.rs`, GitHub, npm, PyPI, Twitter/X, crates.io, etc.

---

### 3. Exhaustive & Interactive Web Tasks (`firecrawl` skill)
Escalate to `firecrawl` CLI (via `bash`) **only** when `read` fails/gets blocked, or when the task demands complex browser interactions:
- **`read` Fails / Blocked**: Anti-bot challenge, Cloudflare, 403/429, or unrendered JS SPA body -> `firecrawl scrape "<URL>" --only-main-content -o .firecrawl/page.md` (add `--wait-for <ms>` if needed).
- **Target Site Known, Path Unknown**: Map routes first -> `firecrawl map "<URL>" --search "<term>" -o .firecrawl/urls.txt`, then scrape specific targets.
- **Bulk Documentation / Section Crawl**: `firecrawl crawl "<URL>" --include-paths "/docs" --limit 50 --wait -o .firecrawl/crawl.json`.
- **Browser Actions (Clicks, Forms, Auth)**: `firecrawl scrape "<URL>"` -> `firecrawl interact "<prompt>"` -> `firecrawl interact stop`.
- **Autonomous Schema Extraction**: `firecrawl agent "<goal>" --urls "<URL>" --schema '<json>' --wait -o .firecrawl/res.json`.
- **Local Document Parsing (PDF, DOCX, XLSX)**: `firecrawl parse "./doc.pdf" -o .firecrawl/doc.md`.

*Output Rule: Always save Firecrawl outputs to `.firecrawl/` with `-o` to avoid flooding LLM context.*
