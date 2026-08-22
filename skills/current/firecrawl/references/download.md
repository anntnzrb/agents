# Firecrawl Download Reference

Bulk download an entire website or scoped section into a organized local directory hierarchy containing Markdown, extracted assets, and full-page screenshots.

## Command Syntax

```bash
firecrawl x download <url> -y [options]
```

Note: `download` is available under the `firecrawl x` experimental command namespace. Always pass `-y` in automated scripts to avoid interactive confirmation prompts.

## Options & Flags

- `-y, --yes`: Non-interactive mode (automatically confirm site download).
- `--include-paths <paths>`: Comma-separated path prefixes to include (e.g. `/docs,/guides`).
- `--exclude-paths <paths>`: Comma-separated path prefixes to exclude (e.g. `/archive,/changelog`).
- `--limit <number>`: Maximum number of pages to download.
- `--screenshot`: Save a viewport screenshot alongside each scraped page.
- `-f, --format <formats>`: Comma-separated formats to download (`markdown`, `links`, `screenshot`, etc.).
- `-o, --output <path>`: Local target directory (defaults to `.firecrawl/`).

## Recipes

### 1. Download Documentation Section with Screenshots
```bash
firecrawl x download "https://docs.example.com" \
  --include-paths "/docs" \
  --screenshot \
  --limit 30 -y
```

### 2. Multi-Format Asset Mirroring
```bash
# Saves index.md, links.txt, and screenshot.png for each discovered page
firecrawl x download "https://example.com" \
  --format markdown,links \
  --screenshot \
  --limit 20 -y
```

## How It Works

1. **Mapping Phase**: Maps the target domain sitemaps and links to assemble an inventory of target URLs.
2. **Scraping Phase**: Fetches and converts each discovered route into Markdown and assets under the destination directory.
3. Requires authentication (not supported on keyless free tier).
