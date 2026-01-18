---
name: brave-search
description: Fast, lightweight web search and content extraction via Brave Search (HTML scrape). Use for quick lookups, scoping, or lightweight docs/fact checks; optionally pair with exa-search for deep multi-step research when needed.
---

# Brave Search

Use Brave Search for headless web search and content extraction. Avoid browsers.

## Setup

Assume `SKILL_DIR` points to this skill folder.

```bash
bun --cwd "$SKILL_DIR" install
```

No API key required (HTML scrape).

Scripts: run `bun --cwd "$SKILL_DIR" scripts/doctor.ts` for a quick check.

References: see `references/tooling.md` and `references/flows.md`.

Assets: `assets/query-templates.json` contains reusable query templates.

## Tools

### search

```bash
bun --cwd "$SKILL_DIR" search.ts "query"                    # Basic search (5 results)
bun --cwd "$SKILL_DIR" search.ts "query" -n 10              # More results
bun --cwd "$SKILL_DIR" search.ts "query" --content          # Include page content as markdown
bun --cwd "$SKILL_DIR" search.ts "query" -n 3 --content     # Combined
```

Options:
- `-n <num>`
- `--content`

### content

```bash
bun --cwd "$SKILL_DIR" content.ts https://example.com/article
```

Fetch a URL and extract readable content as markdown.

## Output Format

```
--- Result 1 ---
Title: Page Title
Link: https://example.com/page
Snippet: Description from search results
Content: (if --content flag used)
  Markdown content extracted from the page...

--- Result 2 ---
...
```
