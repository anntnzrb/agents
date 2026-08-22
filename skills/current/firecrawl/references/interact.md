# Firecrawl Interact Reference

Drive live browser sessions on previously scraped pages. Execute natural language actions or precise script automation (Node/Playwright, Python, or Bash).

## Command Syntax

```bash
# First scrape target to initialize session
firecrawl scrape "<url>" [options]

# Then interact with the active session
firecrawl interact "<prompt>" [options]
# Or with explicit scrape ID
firecrawl interact "<scrape-id>" "<prompt>" [options]

# Terminate session
firecrawl interact stop
```

## Options & Flags

- `-p, --prompt <text>`: Natural language prompt directing browser action.
- `-c, --code <code>`: Raw code to execute in live browser context.
- `--node`: Execute code as Node.js / Playwright script (default).
- `--python`: Execute code as Python Playwright script.
- `--bash`: Execute shell command (e.g. `agent-browser`).
- `-s, --scrape-id <id>`: Target specific scrape job session ID.
- `--timeout <seconds>`: Action timeout in seconds (default: 30s).
- `-o, --output <path>`: Save interaction result to file.
- `--json`: Format output as JSON.

## Browser State & Profiles

Use `--profile <name>` during the initial scrape to persist cookies, localStorage, and session tokens across subsequent runs:

```bash
# 1. Login and save persistent profile
firecrawl scrape "https://app.example.com/login" --profile my-workspace
firecrawl interact "Fill in email field with 'dev@example.com', password with 'secret', and click Log In"

# 2. Re-use authenticated profile in later session
firecrawl scrape "https://app.example.com/billing" --profile my-workspace
firecrawl interact "Extract current unbilled invoice amount"

# 3. Read-only session (prevent modifying stored profile state)
firecrawl scrape "https://app.example.com/dashboard" --profile my-workspace --no-save-changes
```

## Recipes

### 1. Multi-Step Form Submission
```bash
firecrawl scrape "https://example.com/contact"
firecrawl interact "Fill name with 'Alice', message with 'Inquiry', and submit the form"
firecrawl interact "Verify success confirmation message"
firecrawl interact stop
```

### 2. Node/Playwright Script Execution
```bash
firecrawl scrape "https://example.com/interactive-table"
firecrawl interact --code "await page.click('button.expand-all'); await page.waitForTimeout(1000);" --node
firecrawl interact stop
```

## Best Practices

- Always run `firecrawl interact stop` when finished to free server-side browser resources.
- Scrape sessions expire after approximately 10 minutes of inactivity; re-scrape if a session expires.
- For non-interactive pages, prefer standard `scrape --actions` before escalating to full `interact`.
