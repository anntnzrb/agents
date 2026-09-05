---
name: web-ops
description: Unified web router for external reading, deep scraping escalation, and live web search
condition:
  - '\bomp-search(?:/scripts/cli\.ts)?\b|\bfirecrawl(?:-cli(?:@[^\s]+)?)?\s+(?:scrape|search|crawl|map|interact|agent|parse)\b|(?:^|[;&|]\s*)(?:curl|wget)\s'
scope:
  - tool:bash
interruptMode: never
---
# Web operations routing

- For a named structured source or platform task, load its owning skill through `research`. Benchmark CLIs and `x-research` own their source contracts; do not replace them with generic scraping.
- For an ordinary known page, try `read` first. For open-web discovery in OMP, load `omp-search` and use its documented `bun <skill-dir>/scripts/cli.ts` entrypoint through `bash`.
- Load `firecrawl` when `read` is blocked or cannot render the source, or the task explicitly needs mapping, crawling, extraction, or browser interaction. Follow the skill's command and storage contract instead of guessing flags.
- A blocked request is evidence about that route and environment, not a permanent platform ban. Use the owning skill's fallback; do not cycle through mirrors or repeatedly retry an unchanged blocked route.
- Preserve source URLs, dates, scope, completeness, and uncertainty. Search-provider summaries are not verbatim source quotations. Corroborate material claims with primary sources where available.
- Routing does not grant permission to install tools, change credentials, spend credits, write files, or submit forms. Respect the task's authorization and read-only constraints. If a route requires forbidden side effects, choose a permitted route or report the prerequisite.
