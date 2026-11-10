# Firecrawl Recipes

Note: Command names and flag spellings in this document are illustrative and may drift across CLI versions. The agent must confirm exact arguments with `uv run --script <skill-dir>/scripts/cli.py <command> --help` before executing. Steps and intent are the primary guide; commands are secondary.

## Contents

- [Hydrate JS-heavy pages](#1-hydrate-and-extract-js-heavy-spas-thin-page-recovery)
- [Debug errors](#2-debug-an-invariant-error-string-in-issues-and-prs)
- [Mirror documentation](#3-mirror-documentation-subtree-and-grep-locally)
- [Map routes](#4-map-domain-routes-before-crawling)
- [Drive interactions](#5-drive-multi-step-browser-interactions)
- [Parse documents](#6-parse-complex-local-documents)
- [Monitor pages](#7-monitor-content-changes-on-critical-pages)
- [Find structured records](#8-get-structured-records-through-alexandria)
- [Scrape known URLs](#9-scrape-known-urls)

## 1. Hydrate and Extract JS-Heavy SPAs (Thin Page Recovery)

When a simple fetch or scrape returns an empty shell, hydration skeleton, or cookie wall, use Firecrawl's browser rendering engine to let client-side JavaScript finish executing.

### Steps
1. Run `uv run --script <skill-dir>/scripts/cli.py scrape --help` to verify the latest hydration and delay flags.
2. Run scrape specifying wait time (e.g. `--wait-for 3000`), routing output to `.firecrawl/`. Main content filtering is the default; use `--full-page` to include navigation and footers.
3. Inspect the saved file locally with grep, head, or jq instead of dumping raw content into context.

### Illustrative command
```sh
uv run --script <skill-dir>/scripts/cli.py scrape "<url>" \
  --wait-for 3500 \
  -o .firecrawl/<name>.md
```

## 2. Debug an Invariant Error String in Issues and PRs

When encountering cryptic runtime panics, framework regressions, or type errors, search the developer index for exact matches across primary sources (merged PRs, issues, commits, and curated docs).

### Steps
1. Run `uv run --script <skill-dir>/scripts/cli.py developer --help` to check query and limit flags.
2. Execute developer search with the invariant error string, redirecting output to a file under `.firecrawl/`.
3. If strict repository, artifact-type, or doc-source filtering is necessary, call the REST developer search endpoint with bearer auth. Read its current request fields in the Firecrawl API reference first; do not guess them.
4. Read the top returned passages to inspect fixes, workarounds, or tracking issues.

### Illustrative command
```sh
uv run --script <skill-dir>/scripts/cli.py developer "<exact error string>" \
  --limit 5 \
  -o .firecrawl/<name>.json
```

## 3. Mirror Documentation Subtree and Grep Locally

Download a documentation section into local files to enable fast offline searching, regex matching, or multi-file review.

### Steps
1. Check credit balance with `uv run --script <skill-dir>/scripts/cli.py credit-usage` to ensure sufficient credits.
2. Check `uv run --script <skill-dir>/scripts/cli.py x download --help` for path scoping and format options.
3. Download the target section with path limits and non-interactive confirmation (`-y`).
4. Inspect the resulting `.firecrawl/` directory structure using local file tools (`read`, `grep`, `glob`).

### Illustrative command
```sh
uv run --script <skill-dir>/scripts/cli.py x download "<docs-root-url>" \
  --include-paths "<path-prefix>" \
  --limit 25 \
  -y
```

## 4. Map Domain Routes Before Crawling

Avoid blind crawls that waste time and credits on irrelevant sections (e.g. changelogs, marketing pages, localized copies).

### Steps
1. Run `uv run --script <skill-dir>/scripts/cli.py map --help` to check search and depth options.
2. Run map targeting the domain, filtering by keyword if applicable, and save to a file.
3. Review discovered URLs with grep or jq to identify the exact path prefixes needed.
4. Scrape or crawl only the confirmed URLs.

### Illustrative command
```sh
uv run --script <skill-dir>/scripts/cli.py map "<site-url>" \
  --search "<keyword>" \
  --limit 50 \
  -o .firecrawl/<name>-routes.json
```

## 5. Drive Multi-Step Browser Interactions

When target content requires user interaction (clicking buttons, expanding accordions, tab switching, or form filling).

### Steps
1. Run `uv run --script <skill-dir>/scripts/cli.py interact --help` to inspect interactive commands.
2. Execute the initial scrape to establish a session.
3. Run interaction prompts or sandbox code against the active scrape ID.
4. Stop the interactive session when finished.

### Illustrative commands
```sh
uv run --script <skill-dir>/scripts/cli.py scrape "<url>"
uv run --script <skill-dir>/scripts/cli.py interact "<what to click or fill>"
uv run --script <skill-dir>/scripts/cli.py interact stop
```

## 6. Parse Complex Local Documents

Extract clean markdown or answer structured questions from local binary files (PDFs, spreadsheets, DOCX).

### Steps
1. Run `uv run --script <skill-dir>/scripts/cli.py parse --help` to inspect format and query options.
2. Parse the local file directly, directing output to `.firecrawl/`.
3. Read the parsed output or review inline answers.

### Illustrative command
```sh
uv run --script <skill-dir>/scripts/cli.py parse "<local-file>" \
  -Q "<question about the document>" \
  -o .firecrawl/<name>.md
```

## 7. Monitor Content Changes on Critical Pages

Set up periodic checks to detect page changes, price adjustments, or release announcements.

### Steps
1. Run `uv run --script <skill-dir>/scripts/cli.py monitor create --help` to check schedule and alert options.
2. Create a monitor with the target URL, frequency, and alert goal.
3. Inspect monitor checks or diffs using `monitor checks` and `monitor check`.

### Illustrative command
```sh
uv run --script <skill-dir>/scripts/cli.py monitor create \
  --name "<monitor-name>" \
  --goal "<what change matters>" \
  --page "<url>" \
  -o .firecrawl/<name>-monitor.json
```

## 8. Get Structured Records Through Alexandria

For structured records, listings, transcripts, or datasets, check Alexandria for a ready-made workflow, data API, or index before scraping pages or running `agent`. Discovery is free of side effects; only Scrape executes a tool.

### Steps
1. Run `uv run --script <skill-dir>/scripts/cli.py search --help`, `list --help`, and `scrape --help` to confirm discovery and execution flags.
2. Search with the user's actual question. `search alexandria` returns tools only; `find-tools <url>` matches tools to a known website.
3. Inspect the selected tool's contract with `list <provider> <capability> --pretty`. Honor `required` inputs and `requiresOneOf` groups, read the example request and response, and use `response.key` to locate records.
4. Execute with `scrape <provider>/<capability> --options '<JSON matching the contract>'`, saving output under `.firecrawl/`. Check each result for errors, not just the exit status.
5. If no tool covers the market or required inputs, fall back to web results. Do not probe adjacent paid tools for coverage.

With an API key, search includes Alexandria even when `--sources` omits it. `--no-domain-tools` disables domain matches, not semantic tool matches. Keyless search returns web results only.

### Illustrative command
```sh
uv run --script <skill-dir>/scripts/cli.py search alexandria "<data you need>" -o .firecrawl/<name>-tools.json
uv run --script <skill-dir>/scripts/cli.py list "<provider>" "<capability>" --pretty
uv run --script <skill-dir>/scripts/cli.py scrape "<provider>/<capability>" \
  --options '<input JSON>' \
  -o .firecrawl/<name>.json
```

## 9. Scrape known URLs

Use `scrape --format json --schema '<JSON schema>'` for structured fields from one page. For a large schema, use `--schema-file <file>`. The extracted result is under `.json` in the output.

For a few markdown pages, `scrape <url> <url>` saves each page under `.firecrawl/` and ignores `-o`. For many URLs, other formats, structured extraction, or a webhook, use `batch-scrape` instead:

```sh
uv run --script <skill-dir>/scripts/cli.py batch-scrape --urls-file <urls-file> --format markdown,links --wait -o .firecrawl/batch.json
```

The file contains one URL per line and may contain `#` comments. Results are in `.data[]`, with `metadata.sourceURL` identifying each page. Check `batch-scrape --help` for schema, webhook, status, and cancellation options.
