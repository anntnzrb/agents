# Firecrawl Developer Index Reference

Search primary sources across software engineering: GitHub issues, merged pull requests, repository READMEs, and technical documentation.

## Command Syntax

```bash
firecrawl developer "<query>" [options]
```

## Options & Flags

- `--limit <number>`: Number of results to return (default: 10, max: 100).
- `--skills-only`: Search only indexed agent-skill files.
- `-o, --output <path>`: Save results to disk.
- `--json`: Format output as JSON.
- `--pretty`: Pretty-print JSON.

## Why Developer Index over Web Search

1. **Passages vs Links**: Returns verbatim markdown passages (preserving tables, error messages, and code snippets) rather than generic SEO snippets.
2. **Primary Source Authority**: A merged PR that implemented a fix or a README contract is authoritative, whereas a third-party blog post is often outdated.
3. **Prefix Artifacts**: Each result `id` identifies the artifact kind (`issue:`, `pull_request:`, `readme:`, `doc:`).

## Strategy Matrix

- **Exact Error Messages / Stack Traces**: Search the invariant error string and package name. (e.g. `firecrawl developer "TSError: Cannot find module '@effect/schema'"`).
- **Bug Fix Status**: Search for the issue and follow up on merged pull requests. Merged PRs represent the current behavior.
- **Contract & Defaults**: API contracts ("default timeout", "signature") are best found in `doc:` and `readme:` artifacts.
- **Ecosystem / Broad Libraries**: If querying broader library comparisons without public indexed repo docs, escalate to open web search via `firecrawl search`.

## Recipes

### 1. Find Bug Fix or Issue Resolution
```bash
firecrawl developer "tokio select! panic with biased branch" --limit 5 --json --pretty -o .firecrawl/tokio-issue.json
```

### 2. Check Specific Library API Contract
```bash
firecrawl developer "bun spawn stdout pipe ignore options" --limit 5 -o .firecrawl/bun-spawn.json --json
```
