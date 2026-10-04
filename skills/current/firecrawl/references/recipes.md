# Firecrawl Recipes

Note: Command names and flag spellings in this document are illustrative and may drift across CLI versions. The agent must confirm exact arguments with `bun x firecrawl-cli@latest <command> --help` before executing. Steps and intent are the primary guide; commands are secondary.

## 1. Hydrate and Extract JS-Heavy SPAs (Thin Page Recovery)

When a simple fetch or scrape returns an empty shell, hydration skeleton, or cookie wall, use Firecrawl's browser rendering engine to let client-side JavaScript finish executing.

### Steps
1. Run `bun x firecrawl-cli@latest scrape --help` to verify the latest hydration and delay flags.
2. Run scrape specifying wait time (e.g. `--wait-for 3000`) and main content filtering, routing output to `.firecrawl/`.
3. Inspect the saved file locally with grep, head, or jq instead of dumping raw content into context.

### Illustrative command
```sh
bun x firecrawl-cli@latest scrape "<url>" \
  --only-main-content \
  --wait-for 3500 \
  -o .firecrawl/<name>.md
```

## 2. Debug an Invariant Error String in Issues and PRs

When encountering cryptic runtime panics, framework regressions, or type errors, search the developer index for exact matches across primary sources (merged PRs, issues, commits, and curated docs).

### Steps
1. Run `bun x firecrawl-cli@latest developer --help` to check query and limit flags.
2. Execute developer search with the invariant error string, redirecting output to a file under `.firecrawl/`.
3. If strict repository, artifact-type, or doc-source filtering is necessary, call the REST developer search endpoint with bearer auth. Read its current request fields in the Firecrawl API reference first; do not guess them.
4. Read the top returned passages to inspect fixes, workarounds, or tracking issues.

### Illustrative command
```sh
bun x firecrawl-cli@latest developer "<exact error string>" \
  --limit 5 \
  -o .firecrawl/<name>.json
```

## 3. Mirror Documentation Subtree and Grep Locally

Download a documentation section into local files to enable fast offline searching, regex matching, or multi-file review.

### Steps
1. Check credit balance with `bun x firecrawl-cli@latest credit-usage` to ensure sufficient credits.
2. Check `bun x firecrawl-cli@latest x download --help` for path scoping and format options.
3. Download the target section with path limits and non-interactive confirmation (`-y`).
4. Inspect the resulting `.firecrawl/` directory structure using local file tools (`read`, `grep`, `glob`).

### Illustrative command
```sh
bun x firecrawl-cli@latest x download "<docs-root-url>" \
  --include-paths "<path-prefix>" \
  --limit 25 \
  -y
```

## 4. Map Domain Routes Before Crawling

Avoid blind crawls that waste time and credits on irrelevant sections (e.g. changelogs, marketing pages, localized copies).

### Steps
1. Run `bun x firecrawl-cli@latest map --help` to check search and depth options.
2. Run map targeting the domain, filtering by keyword if applicable, and save to a file.
3. Review discovered URLs with grep or jq to identify the exact path prefixes needed.
4. Scrape or crawl only the confirmed URLs.

### Illustrative command
```sh
bun x firecrawl-cli@latest map "<site-url>" \
  --search "<keyword>" \
  --limit 50 \
  -o .firecrawl/<name>-routes.json
```

## 5. Drive Multi-Step Browser Interactions

When target content requires user interaction (clicking buttons, expanding accordions, tab switching, or form filling).

### Steps
1. Run `bun x firecrawl-cli@latest interact --help` to inspect interactive commands.
2. Execute the initial scrape to establish a session.
3. Run interaction prompts or sandbox code against the active scrape ID.
4. Stop the interactive session when finished.

### Illustrative commands
```sh
bun x firecrawl-cli@latest scrape "<url>"
bun x firecrawl-cli@latest interact "<what to click or fill>"
bun x firecrawl-cli@latest interact stop
```

## 6. Parse Complex Local Documents

Extract clean markdown or answer structured questions from local binary files (PDFs, spreadsheets, DOCX).

### Steps
1. Run `bun x firecrawl-cli@latest parse --help` to inspect format and query options.
2. Parse the local file directly, directing output to `.firecrawl/`.
3. Read the parsed output or review inline answers.

### Illustrative command
```sh
bun x firecrawl-cli@latest parse "<local-file>" \
  -Q "<question about the document>" \
  -o .firecrawl/<name>.md
```

## 7. Monitor Content Changes on Critical Pages

Set up periodic checks to detect page changes, price adjustments, or release announcements.

### Steps
1. Run `bun x firecrawl-cli@latest monitor create --help` to check schedule and alert options.
2. Create a monitor with the target URL, frequency, and alert goal.
3. Inspect monitor checks or diffs using `monitor checks` and `monitor check`.

### Illustrative command
```sh
bun x firecrawl-cli@latest monitor create \
  --name "<monitor-name>" \
  --goal "<what change matters>" \
  --page "<url>" \
  -o .firecrawl/<name>-monitor.json
```

## 8. Get Structured Records Through Alexandria

For structured records, listings, transcripts, or datasets, check Alexandria for a ready-made workflow, data API, or index before scraping pages or running `agent`. Discovery is free of side effects; only Scrape executes a tool.

### Steps
1. Run `bun x firecrawl-cli@latest search --help`, `list --help`, and `scrape --help` to confirm discovery and execution flags.
2. Search with the user's actual question. `search alexandria` returns tools only; `find-tools <url>` matches tools to a known website.
3. Inspect the selected tool's contract with `list <provider> <capability> --pretty`. Honor `required` inputs and `requiresOneOf` groups, read the example request and response, and use `response.key` to locate records.
4. Execute with `scrape <provider>/<capability> --options '<JSON matching the contract>'`, saving output under `.firecrawl/`. Check each result for errors, not just the exit status.
5. If no tool covers the market or required inputs, fall back to web results. Do not probe adjacent paid tools for coverage.

### Illustrative command
```sh
bun x firecrawl-cli@latest search alexandria "<data you need>" -o .firecrawl/<name>-tools.json
bun x firecrawl-cli@latest list "<provider>" "<capability>" --pretty
bun x firecrawl-cli@latest scrape "<provider>/<capability>" \
  --options '<input JSON>' \
  -o .firecrawl/<name>.json
```
