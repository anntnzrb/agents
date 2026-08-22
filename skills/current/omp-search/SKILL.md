---
name: omp-search
description: "Use when headless web search needs OMP's provider routing, explicit provider choice, or structured JSON output."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb

---

# OMP Search

Use this skill when an agent needs live web search through the installed OMP CLI, especially for recency-sensitive research, explicit provider selection, or unattended execution.

## Entry point

Run the cross-platform wrapper; do not invoke a shell, source an environment file, or scrape OMP's terminal panel yourself:

```text
bun <skill-dir>/scripts/cli.ts "<query>"
```

The wrapper locates `omp` on `PATH` or uses `OMP_BIN`, preserves the caller's working directory and OMP profile, and emits one JSON object to stdout.

## Workflow

1. Pass the complete search question as positional query words
2. By default, the search skill dynamically discovers all active, configured search providers from OMP's configuration, queries them concurrently in parallel, deduplicates sources across the web, and aggregates all provider-attributed intelligence for the calling agent to evaluate and synthesize
3. Pass `--providers <p1,p2,...>` to select a custom subset of providers in parallel, or `--provider <name>` / `--single` to force a single specific provider
4. Use `--recency day|week|month|year` for freshness and `--limit N` (minimum 2; defaults to 2) to bound sources per provider
5. Accept the default compact answer for agent context efficiency; pass `--full` when the complete answer matters
6. Preserve `ok`, `query`, `providers`, `providers_count`, `sources`, `sources_count`, `answer`, `exit_code`, and `error` in the caller's result. Do not expose environment values
OMP loads its own dotenv/auth configuration. Never read, copy, print, or synthesize provider secrets in this skill. Query directives such as `site:`, `after:`, and `before:` may be included in the query.

## Output contract

Success returns:
```json
{
  "ok": true,
  "query": "...",
  "provider": "ProviderA+ProviderB",
  "providers": ["ProviderA", "ProviderB"],
  "providers_count": 2,
  "answer": "### [ProviderA]\n...\n\n### [ProviderB]\n...",
  "sources": [{"title": "...", "domain": "...", "age": "..."}],
  "sources_count": 4,
  "truncated": false,
  "compact": true,
  "parsed": true,
  "exit_code": 0
}
```
`age` may be null. OMP's terminal renderer does not reliably expose source URLs, so do not invent a `url` field. Pass `--include-raw` only when debugging parser behavior. The raw field is ANSI-stripped but may include launcher diagnostics.

Failure returns the same query context with `ok: false`, an `error` object, and the child or wrapper `exit_code`. Exit `127` means `omp` is unavailable; exit `124` means the outer timeout fired; OMP's nonzero exit is preserved. Usage/configuration errors return `2`.

## Examples

```text
bun <skill-dir>/scripts/cli.ts "latest Bun JavaScript runtime release" --recency week --limit 3
bun <skill-dir>/scripts/cli.ts "ancient history of the Antikythera mechanism" --providers exa,parallel
bun <skill-dir>/scripts/cli.ts "current TypeScript release" --provider brave --full
```

## Runtime notes

- The wrapper is non-interactive and uses argument arrays; never interpolate a query into shell syntax
- The default timeout is 300 seconds because automatic provider fallback can outlive one provider request
- OMP may print dependency-sync noise before its panel; the wrapper removes that from structured fields
- If automatic search fails, retry once with a configured explicit provider and report the actual provider error

## Validation

```text
bun <skill-dir>/scripts/cli.ts --help
bun test <skill-dir>/test/
uv run --script <skill-creator-dir>/scripts/cli.py quick-validate <skill-dir>
```
