# Firecrawl Map Reference

Discover and enumerate all indexed URLs on a domain rapidly using sitemaps and site graphs without scraping page bodies.

## Command Syntax

```bash
firecrawl map <url> [options]
```

## Options & Flags

- `--search <query>`: Filter discovered URLs by fuzzy keyword or route pattern.
- `--limit <number>`: Maximum number of URLs to discover (1 to 5000, default: 5000).
- `--include-subdomains`: Discover URLs across all subdomains.
- `--sitemap <mode>`: Sitemap handling mode (`include`, `skip`, `only`).
- `--ignore-query-parameters`: Deduplicate URLs with different query strings.
- `--wait`: Block until mapping completes.
- `--timeout <seconds>`: Timeout in seconds.
- `-o, --output <path>`: Write URL list to file.
- `--json`: Output as structured JSON array.
- `--pretty`: Pretty-print JSON.

## The Map + Scrape Pattern

Mapping is lightweight and fast. Instead of crawling blind, map the site first to identify the exact target URLs, then scrape only the relevant ones.

```bash
# 1. Map all documentation pages matching "middleware"
firecrawl map "https://hono.dev" --search "middleware" -o .firecrawl/hono-middleware-urls.txt

# 2. Inspect found URLs
head -10 .firecrawl/hono-middleware-urls.txt

# 3. Scrape the specific match
firecrawl scrape "https://hono.dev/docs/guides/middleware" --only-main-content -o .firecrawl/middleware.md
```

## Recipes

### 1. Discover All Subdomain Endpoints
```bash
firecrawl map "https://github.com" --include-subdomains --limit 1000 --json -o .firecrawl/github-map.json
```

### 2. Sitemap Only Discovery
```bash
firecrawl map "https://stripe.com" --sitemap only --search "payments" -o .firecrawl/stripe-urls.txt
```

## Constraints

- Requires authentication (not available on keyless tier).
- Map operations return URLs only, not page content.
