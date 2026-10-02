---
name: parallel
description: "Use when using Parallel for search, deep research, enrichment, monitors, or URL extraction, not site crawling."
license: AGPL-3.0-or-later
compatibility: Requires uv and PARALLEL_API_KEY in the environment.
metadata:
  author: anntnzrb
---

# Parallel

Official Parallel CLI for web search, cited deep research, entity discovery, data enrichment, and topic monitoring.

## Public entrypoint

```bash
uvx --from "parallel-web-tools[cli]" parallel-cli <command> [options] [arguments]
```

Requires `uv` and `PARALLEL_API_KEY` in the environment. Run the CLI auth command to verify active credentials.

## Discovery

Live `--help` is the only authority for available commands, subcommands, and flags.

Always inspect live help before running commands in a session:
1. Run `uvx --from "parallel-web-tools[cli]" parallel-cli --help` to list top-level commands.
2. Run `uvx --from "parallel-web-tools[cli]" parallel-cli <command> --help` before first use of any command to inspect arguments, options, and defaults.
3. For multi-tier commands such as research, inspect available processor tiers via the research CLI help before launching runs.

Do not guess flag names or rely on memorized schemas. Live help reflects current runtime behavior.

## Core capabilities

Route tasks to the appropriate command based on objective:

- **Web search**: Find public web pages, articles, and documentation with keyword or natural language queries, domain filters, date cutoffs, or fast/deep retrieval modes.
- **Deep research**: Synthesize comprehensive, cited reports from multiple sources for open-ended or complex technical questions.
- **Entity discovery (FindAll)**: Discover ranked lists of entities matching natural language criteria (such as companies, tools, or people).
- **Data enrichment**: Augment existing datasets, schemas, or entity lists with fresh attributes looked up from the web.
- **Semantic topic monitoring**: Track topics, events, or target domains over time with automated change alerts.
- **Content extraction**: Extract clean markdown or structured excerpts from known URLs.
- **Saved research recall**: Query past research tasks, monitors, or discoveries saved in Parallel memory.

## Durable rules

- **Keep context compact**: CLI output can be extensive. For large queries, deep research reports, or entity lists, use output flags to save results directly to a file on disk (or redirect stdout), then inspect excerpts or target fields with jq. Never dump full JSON blobs into conversation context.
- **Query strategy**: Several short, focused queries covering distinct angles beat one long, overloaded query. Start with a few results, review excerpts, and extract full content only from the top one or two authoritative URLs.
- **Rendering fallback**: When extracting content from a page that requires client-side JavaScript execution, if the returned content is empty or incomplete, use a rendering scraper.
- **Use built-in polling**: Long-running jobs (deep research, findall runs, batch enrichments) offer built-in polling commands. Let the CLI wait and poll rather than constructing manual sleep loops.
- **Check processor costs before deep research**: Available research processors range from fast, economical tiers to intensive multi-hour tiers. Always inspect the processor list and characteristics via the research CLI help first. Select the lowest tier that adequately covers the query depth.

## Follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Workflow recipes | `references/recipes.md` | Running multi-step search, deep research, entity extraction, or monitoring workflows |
