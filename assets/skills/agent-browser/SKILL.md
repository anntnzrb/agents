---
name: agent-browser
description: Browser automation CLI for AI agents. Use when the user needs to interact with websites, including navigating pages, filling forms, clicking buttons, taking screenshots, extracting data, testing web apps, or automating any browser task. Triggers include requests to "open a website", "fill out a form", "click a button", "take a screenshot", "scrape data from a page", "test this web app", "login to a site", "automate browser actions", or any task requiring programmatic web interaction.
license: GPL-3.0-or-later
metadata:
  author: anntnzrb
allowed-tools: ""
disable-model-invocation: true
---

# Browser Automation with agent-browser

Use `agent-browser` for browser tasks: navigate sites, fill forms, click controls, authenticate, capture screenshots/PDFs, extract page data, test web apps, compare page states, or automate repeatable browser interactions.

## Entry Point

Canonical entry:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. NEVER rely on shell functions, shell sourcing, executable bits, or shebang dispatch. The wrapper delegates to `nix run github:numtide/llm-agents.nix#agent-browser -- ...` and preserves exit codes.

Examples use `agent-browser ...` as readable shorthand for `uv run --script <skill-dir>/scripts/cli.py ...`; invoke the canonical command in actual tool calls unless the environment already provides an equivalent `agent-browser` executable.

<critical>
- Before each new browser task, you MUST run `uv run --script <skill-dir>/scripts/cli.py close` once to clear stale sessions.
- After every browser task, you MUST run `uv run --script <skill-dir>/scripts/cli.py close`, even when a command fails.
- On interruption, uncertainty, stale daemon state, or unknown browser state, you MUST run `uv run --script <skill-dir>/scripts/cli.py close` immediately, then restart from `open`.
- NEVER infer missing authentication from absent environment variables alone. agent-browser MAY authenticate via its auth vault, saved browser state, or an existing session. Verify auth with real commands: `agent-browser auth list`, `agent-browser state list`, or the actual login flow.
- Element refs such as `@e1` are snapshot-local. After navigation, reload, DOM mutation, modal open/close, filtering, pagination, or any interaction that may change the tree, you MUST run `agent-browser snapshot -i` again before using refs.
</critical>

<workflow>
Every browser automation MUST follow this loop:

1. Navigate: `agent-browser open <url>`
2. Snapshot: `agent-browser snapshot -i` to obtain current element refs.
3. Interact: click, fill, select, check, type, scroll, or wait using current refs.
4. Re-snapshot: after navigation or DOM changes, refresh refs and inspect the result.

```text
agent-browser open https://example.com/form
agent-browser snapshot -i
# Output: @e1 [input type="email"], @e2 [input type="password"], @e3 [button] "Submit"

agent-browser fill @e1 "user@example.com"
agent-browser fill @e2 "password123"
agent-browser click @e3
agent-browser wait --load networkidle
agent-browser snapshot -i
```
</workflow>

## Command Chaining

You MAY chain commands with `&&` in one shell invocation. The browser persists between commands via a background daemon, so chaining is safe only when later commands need no unobserved intermediate output.

```text
# Chain open + wait + snapshot in one call
agent-browser open https://example.com && agent-browser wait --load networkidle && agent-browser snapshot -i

# Chain multiple interactions
agent-browser fill @e1 "user@example.com" && agent-browser fill @e2 "password123" && agent-browser click @e3

# Navigate and capture
agent-browser open https://example.com && agent-browser wait --load networkidle && agent-browser screenshot page.png
```

Use `&&` only when intermediate output is irrelevant, such as open + wait + screenshot. Run commands separately when output determines the next action, especially `snapshot -i` before ref-based interaction.

## Essential Commands

```text
# Navigation
agent-browser open <url>              # Navigate (aliases: goto, navigate)
agent-browser close                   # Close browser

# Snapshot
agent-browser snapshot -i             # Interactive elements with refs (recommended)
agent-browser snapshot -i -C          # Include cursor-interactive elements (divs with onclick, cursor:pointer)
agent-browser snapshot -s "#selector" # Scope to CSS selector

# Interaction (use @refs from snapshot)
agent-browser click @e1               # Click element
agent-browser click @e1 --new-tab     # Click and open in new tab
agent-browser fill @e2 "text"         # Clear and type text
agent-browser type @e2 "text"         # Type without clearing
agent-browser select @e1 "option"     # Select dropdown option
agent-browser check @e1               # Check checkbox
agent-browser press Enter             # Press key
agent-browser keyboard type "text"    # Type at current focus (no selector)
agent-browser keyboard inserttext "text"  # Insert without key events
agent-browser scroll down 500         # Scroll page
agent-browser scroll down 500 --selector "div.content"  # Scroll within a specific container

# Get information
agent-browser get text @e1            # Get element text
agent-browser get url                 # Get current URL
agent-browser get title               # Get page title

# Wait
agent-browser wait @e1                # Wait for element
agent-browser wait --load networkidle # Wait for network idle
agent-browser wait --url "**/page"    # Wait for URL pattern
agent-browser wait 2000               # Wait milliseconds

# Downloads
agent-browser download @e1 ./file.pdf          # Click element to trigger download
agent-browser wait --download ./output.zip     # Wait for any download to complete
agent-browser --download-path ./downloads open <url>  # Set default download directory

# Capture
agent-browser screenshot              # Screenshot to temp dir
agent-browser screenshot --full       # Full page screenshot
agent-browser screenshot --annotate   # Annotated screenshot with numbered element labels
agent-browser pdf output.pdf          # Save as PDF

# Diff (compare page states)
agent-browser diff snapshot                          # Compare current vs last snapshot
agent-browser diff snapshot --baseline before.txt    # Compare current vs saved file
agent-browser diff screenshot --baseline before.png  # Visual pixel diff
agent-browser diff url <url1> <url2>                 # Compare two pages
agent-browser diff url <url1> <url2> --wait-until networkidle  # Custom wait strategy
agent-browser diff url <url1> <url2> --selector "#main"  # Scope to element
```

## Common Patterns

### Form Submission

```text
agent-browser open https://example.com/signup
agent-browser snapshot -i
agent-browser fill @e1 "Jane Doe"
agent-browser fill @e2 "jane@example.com"
agent-browser select @e3 "California"
agent-browser check @e4
agent-browser click @e5
agent-browser wait --load networkidle
agent-browser snapshot -i
```

### Authentication with Auth Vault

Prefer the auth vault when credentials must be reused. Pipe passwords via stdin to avoid shell history exposure.

```text
# Save credentials once (encrypted with AGENT_BROWSER_ENCRYPTION_KEY)
echo "pass" | agent-browser auth save github --url https://github.com/login --username user --password-stdin

# Login using saved profile (LLM never sees password)
agent-browser auth login github

# List/show/delete profiles
agent-browser auth list
agent-browser auth show github
agent-browser auth delete github
```

### Authentication with State Persistence

Use saved browser state when the login flow establishes cookies, localStorage, OAuth state, or 2FA-bound sessions.

```text
# Login once and save state
agent-browser open https://app.example.com/login
agent-browser snapshot -i
agent-browser fill @e1 "$USERNAME"
agent-browser fill @e2 "$PASSWORD"
agent-browser click @e3
agent-browser wait --url "**/dashboard"
agent-browser state save auth.json

# Reuse in future sessions
agent-browser state load auth.json
agent-browser open https://app.example.com/dashboard
```

### Session Persistence

Use named sessions for automatic cookie/localStorage restore across restarts. Set `AGENT_BROWSER_ENCRYPTION_KEY` when state requires encryption at rest.

```text
# Auto-save/restore cookies and localStorage across browser restarts
agent-browser --session-name myapp open https://app.example.com/login
# ... login flow ...
agent-browser close  # State auto-saved to ~/.agent-browser/sessions/

# Next time, state is auto-loaded
agent-browser --session-name myapp open https://app.example.com/dashboard

# Encrypt state at rest
export AGENT_BROWSER_ENCRYPTION_KEY=$(openssl rand -hex 32)
agent-browser --session-name secure open https://app.example.com

# Manage saved states
agent-browser state list
agent-browser state show myapp-default.json
agent-browser state clear myapp
agent-browser state clean --older-than 7
```

### Data Extraction

Extract only what the task requires. Prefer scoped selectors or refs over whole-page dumps when precision matters.

```text
agent-browser open https://example.com/products
agent-browser snapshot -i
agent-browser get text @e5           # Get specific element text
agent-browser get text body > page.txt  # Get all page text

# JSON output for parsing
agent-browser snapshot -i --json
agent-browser get text @e1 --json
```

### Parallel Sessions

Use separate sessions for concurrent sites, isolated identities, or comparison workflows.

```text
agent-browser --session site1 open https://site-a.com
agent-browser --session site2 open https://site-b.com

agent-browser --session site1 snapshot -i
agent-browser --session site2 snapshot -i

agent-browser session list
```

### Connect to Existing Chrome

Use an existing Chrome only when remote debugging is intentionally enabled or CDP attachment is required.

```text
# Auto-discover running Chrome with remote debugging enabled
agent-browser --auto-connect open https://example.com
agent-browser --auto-connect snapshot

# Or with explicit CDP port
agent-browser --cdp 9222 snapshot
```

### Color Scheme

```text
# Persistent dark mode via flag (applies to all pages and new tabs)
agent-browser --color-scheme dark open https://example.com

# Or via environment variable
AGENT_BROWSER_COLOR_SCHEME=dark agent-browser open https://example.com

# Or set during session (persists for subsequent commands)
agent-browser set media dark
```

### Visual Browser

Use headed mode for debugging, visual QA, highlighting, recording, or profiling.

```text
agent-browser --headed open https://example.com
agent-browser highlight @e1          # Highlight element
agent-browser record start demo.webm # Record session
agent-browser profiler start         # Start Chrome DevTools profiling
agent-browser profiler stop trace.json # Stop and save profile (path optional)
```

`AGENT_BROWSER_HEADED=1` enables headed mode via environment variable. Browser extensions work in both headed and headless mode.

### Local Files

```text
# Open local files with file:// URLs
agent-browser --allow-file-access open file:///path/to/document.pdf
agent-browser --allow-file-access open file:///path/to/page.html
agent-browser screenshot output.png
```

### iOS Simulator (Mobile Safari)

Use iOS mode for Mobile Safari workflows. Requirements: macOS with Xcode, Appium (`npm install -g appium && appium driver install xcuitest`). Physical iOS devices work when pre-configured; use `--device "<UDID>"` where UDID is from `xcrun xctrace list devices`.

```text
# List available iOS simulators
agent-browser device list

# Launch Safari on a specific device
agent-browser -p ios --device "iPhone 16 Pro" open https://example.com

# Same workflow as desktop - snapshot, interact, re-snapshot
agent-browser -p ios snapshot -i
agent-browser -p ios tap @e1          # Tap (alias for click)
agent-browser -p ios fill @e2 "text"
agent-browser -p ios swipe up         # Mobile-specific gesture

# Take screenshot
agent-browser -p ios screenshot mobile.png

# Close session (shuts down simulator)
agent-browser -p ios close
```

## Advanced Workflows

Read the advanced reference only when you need content boundaries, allowlists, action policy, output limits, snapshot/screenshot diffing, timeout strategy, ref lifecycle troubleshooting, semantic locators, `eval`, or persistent config behavior.

See [references/advanced.md](references/advanced.md).

## Deep-Dive Documentation

| Reference | When to Use |
|-----------|-------------|
| [references/commands.md](references/commands.md) | Full command reference with all options |
| [references/snapshot-refs.md](references/snapshot-refs.md) | Ref lifecycle, invalidation rules, troubleshooting |
| [references/session-management.md](references/session-management.md) | Parallel sessions, state persistence, concurrent scraping |
| [references/authentication.md](references/authentication.md) | Login flows, OAuth, 2FA handling, state reuse |
| [references/video-recording.md](references/video-recording.md) | Recording workflows for debugging and documentation |
| [references/profiling.md](references/profiling.md) | Chrome DevTools profiling for performance analysis |
| [references/proxy-support.md](references/proxy-support.md) | Proxy configuration, geo-testing, rotating proxies |
| [references/advanced.md](references/advanced.md) | Security controls, diffing, timeouts, `eval`, config, ref lifecycle |

## Experimental: Native Mode

Native mode is experimental. It uses a Rust daemon that communicates with Chrome directly via CDP, bypassing Node.js and Playwright. Use it only when explicitly needed; it is not RECOMMENDED for production.

```text
# Enable via flag
agent-browser --native open example.com

# Enable via environment variable (avoids passing --native every time)
export AGENT_BROWSER_NATIVE=1
agent-browser open example.com
```

The native daemon supports Chromium and Safari via WebDriver. Firefox and WebKit are not yet supported. Core commands such as navigate, snapshot, click, fill, screenshot, cookies, storage, tabs, and eval should behave the same as default mode. You MUST run `agent-browser close` before switching between native and default mode within the same session.

<critical>
At task end, close the browser with `uv run --script <skill-dir>/scripts/cli.py close`. If any browser command output changes the page, invalidates refs, or raises state uncertainty, re-enter the workflow from snapshot or open rather than guessing.
</critical>
