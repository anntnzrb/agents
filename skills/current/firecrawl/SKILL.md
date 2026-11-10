---
name: firecrawl
description: "Use when scraping URLs, crawling or mapping sites, parsing docs, or querying Firecrawl indexes, not for deep research."
license: AGPL-3.0-or-later
compatibility: Requires bun and FIRECRAWL_API_KEY.
---

# Firecrawl

Web scraping, crawling, mapping, document parsing, page interaction, monitoring, and developer/research index queries via Firecrawl CLI.

## Public entrypoint

Run the pinned CLI through bun:
```sh
uv run --script <skill-dir>/scripts/cli.py <command> ...
```

Requires `FIRECRAWL_API_KEY` set in the environment.

## Discover

Live `--help` is the single authority for commands, arguments, and flags:
1. Discover top-level commands:
   ```sh
   uv run --script <skill-dir>/scripts/cli.py --help
   ```
2. Discover options, flags, and arguments before first use of a command in a session:
   ```sh
   uv run --script <skill-dir>/scripts/cli.py <command> --help
   ```

Do not guess flag names or rely on memorized schemas. Live help documents all supported parameters.

## Jobs

Match the intent to a command listed by live `--help`:

- Fetch a known URL, especially JS-heavy pages that come back thin from a plain fetch.
- Use `batch-scrape` for many known URLs, non-markdown formats, JSON extraction, or a webhook.
- Crawl a site or path subtree, or map a domain's URLs before crawling.
- Mirror a docs site to local disk, then search it with local tools.
- Parse local documents (PDF, Office, HTML).
- Drive a live browser session: click, fill forms, paginate.
- Track page changes on a schedule.
- Find structured records or listings through a ready-made Alexandria workflow, data API, or index, then execute it.
- Look up error strings, GitHub issues and PRs, READMEs, or library docs in the developer index.
- Find US legal or regulatory sources in the government index.
- Search and read scientific papers in the research index.
- Check credit balance; diagnose failed runs.

## Recipes

| Need | Read | When |
| --- | --- | --- |
| Multi-step workflows | `references/recipes.md` | Debugging errors, mirroring doc trees, interactive scraping, structured data through Alexandria, or recurring monitors |

## Durable Rules

- Write results to files under `.firecrawl/` with the CLI's output option; inspect them with `jq` or `grep`. Never stream large payloads into context.
- Check credit usage before large crawls or site downloads.
- Let the CLI wait on async jobs with its own wait options; do not write polling loops.
- When live page state matters, disable cached snapshots with the CLI's max-age option.
- Cap PDF parsing with the scrape page-limit option; each parsed page costs a credit.
- When an `agent` run stops on a pending approval, ask the user before approving the paid provider call. An organization admin must accept provider terms in the [Firecrawl dashboard](https://www.firecrawl.dev/app/settings?tab=data-sources); use `alexandria terms show <provider>` to review them first. Approval does not accept terms.
- The developer command takes a free-form query. For strict filters (repositories, artifact types, doc sources, language, stars), call the REST developer search endpoint; read its current fields in the Firecrawl API reference before building the request.
- Confirm a merged fix is included in the user's release before describing it as installed behavior. Cite the release evidence.
- For US law or regulations, use `gov` with the question, jurisdiction, and date. Use `--limit` for result count; `-k` sets the API key. Read a supplied source URL with `scrape`.
- Narrow `gov` with `--jurisdiction`, `--court`, `--court-type`, `--cites`, or `--domain` when appropriate. Filters can omit relevant pages without index labels; `search --categories gov` does not support these filters.
- Before citing governing law, verify the issuer, jurisdiction, enacted and effective status, and version. Ask for a missing jurisdiction before identifying a rule. Use general search for non-US questions or missing coverage; no results do not prove that no applicable law exists.

## Maintenance

When upstream changes, review its diff, port applicable changes, and update `UPSTREAM.json` with the release commit, tree hashes, and reviewed directories. The wrapper reads the npm version from `release`. Run the skill gates and smoke-test the wrapper after a bump.
