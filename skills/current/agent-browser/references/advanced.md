# Advanced Usage

## Security

Security features opt-in. Default: agent-browser restricts neither navigation, actions, nor output.

### Content boundaries

For AI-agent separation of tool output from untrusted page content, enable `--content-boundaries`:

```bash
export AGENT_BROWSER_CONTENT_BOUNDARIES=1
agent-browser snapshot
# Output:
# --- AGENT_BROWSER_PAGE_CONTENT nonce=<hex> origin=https://example.com ---
# [accessibility tree]
# --- END_AGENT_BROWSER_PAGE_CONTENT nonce=<hex> ---
```

### Domain allowlist

The domain allowlist restricts navigation to trusted domains. `*.example.com` matches `example.com` too. Non-allowed sub-resource, WebSocket, and EventSource requests are blocked; include required CDN domains:

```bash
export AGENT_BROWSER_ALLOWED_DOMAINS="example.com,*.example.com"
agent-browser open https://example.com        # OK
agent-browser open https://malicious.com       # Blocked
```

### Action policy

Use a policy file to gate destructive actions:

```bash
export AGENT_BROWSER_ACTION_POLICY=./policy.json
```

```json
{
  "default": "deny",
  "allow": ["navigate", "snapshot", "click", "scroll", "wait", "get"]
}
```

Auth-vault operations (`auth login`, etc.) bypass action policy; domain allowlist still applies.

### Output limit

```bash
export AGENT_BROWSER_MAX_OUTPUT=50000
```

Limits large-page output and prevents context flooding.

## Diffing

After an action, use `diff snapshot` to verify its effect; it compares the current accessibility tree with the session's last snapshot:

```bash
# Typical workflow: snapshot -> action -> diff
agent-browser snapshot -i          # Take baseline snapshot
agent-browser click @e2            # Perform action
agent-browser diff snapshot        # See what changed (auto-compares to last snapshot)
```

Visual regression or monitoring:

```bash
# Save a baseline screenshot, then compare later
agent-browser screenshot baseline.png
# ... time passes or changes are made ...
agent-browser diff screenshot --baseline baseline.png

# Compare staging vs production
agent-browser diff url https://staging.example.com https://prod.example.com --screenshot
```

`diff snapshot`: `+` additions, `-` removals, like git diff. `diff screenshot`: diff image with changed pixels highlighted red plus mismatch percentage.

## Timeouts and slow pages

Default local-browser Playwright timeout: 25 seconds. Override with `AGENT_BROWSER_DEFAULT_TIMEOUT` in milliseconds. Prefer explicit waits for slow or large pages:

```bash
# Wait for network activity to settle (best for slow pages)
agent-browser wait --load networkidle

# Wait for a specific element to appear
agent-browser wait "#content"
agent-browser wait @e1

# Wait for a specific URL pattern (useful after redirects)
agent-browser wait --url "**/dashboard"

# Wait for a JavaScript condition
agent-browser wait --fn "document.readyState === 'complete'"

# Wait a fixed duration (milliseconds) as a last resort
agent-browser wait 5000
```

For consistently slow sites, run `wait --load networkidle` after `open` before `snapshot`. For slow-rendering elements, wait on `<selector>` or `@ref` directly.

## Session management and cleanup

Concurrent agents/automations MUST use named, isolated sessions:

```bash
# Each agent gets its own isolated session
agent-browser --session agent1 open site-a.com
agent-browser --session agent2 open site-b.com

# Check active sessions
agent-browser session list
```

Always close sessions to prevent leaked processes:

```bash
agent-browser close                    # Close default session
agent-browser --session agent1 close   # Close specific session
```

If a prior session was not closed properly and its daemon remains, run `agent-browser close` before starting.

## Ref lifecycle

Refs (`@e1`, `@e2`, etc.) become invalid when the page changes. Re-snapshot after navigation clicks, form submissions, or dynamic dropdown/modal loading:

```bash
agent-browser click @e5              # Navigates to new page
agent-browser snapshot -i            # MUST re-snapshot
agent-browser click @e1              # Use new refs
```

## Annotated screenshots

`--annotate` overlays numbered labels on interactive elements; `[N]` maps to `@eN`. It also caches refs, enabling immediate interaction without a separate snapshot:

```bash
agent-browser screenshot --annotate
# Output includes the image path and a legend:
#   [1] @e1 button "Submit"
#   [2] @e2 link "Home"
#   [3] @e3 textbox "Email"
agent-browser click @e2              # Click using ref from annotated screenshot
```

Use annotated screenshots for unlabeled icon/visual-only buttons, visual layout or styling verification, canvas/chart elements invisible to text snapshots, or spatial reasoning.

## Semantic locators

When refs are unavailable or unreliable:

```bash
agent-browser find text "Sign In" click
agent-browser find label "Email" fill "user@test.com"
agent-browser find role button click --name "Submit"
agent-browser find placeholder "Search" type "query"
agent-browser find testid "submit-btn" click
```

## JavaScript evaluation

`eval` runs JavaScript in the browser context. Shell quoting can corrupt complex expressions; use `--stdin` or `-b`:

```bash
# Simple expressions work with regular quoting
agent-browser eval 'document.title'
agent-browser eval 'document.querySelectorAll("img").length'

# Complex JS: use --stdin with heredoc (RECOMMENDED)
agent-browser eval --stdin <<'EVALEOF'
JSON.stringify(
  Array.from(document.querySelectorAll("img"))
    .filter(i => !i.alt)
    .map(i => ({ src: i.src.split("/").pop(), width: i.width }))
)
EVALEOF

# Alternative: base64 encoding (avoids all shell escaping issues)
agent-browser eval -b "$(echo -n 'Array.from(document.querySelectorAll("a")).map(a => a.href)' | base64)"
```

Shell processing can corrupt inner double quotes, `!` (history expansion), backticks, and `$()`; `--stdin` and `-b` bypass shell interpretation.

Rules:
- Single-line with no nested quotes: regular `eval 'expression'` is fine.
- Nested quotes, arrow functions, template literals, or multiline: `eval --stdin <<'EVALEOF'`.
- Programmatic/generated scripts: `eval -b` with base64.

## Configuration file

Create `agent-browser.json` in the project root for persistent settings:

```json
{
  "headed": true,
  "proxy": "http://localhost:8080",
  "profile": "./browser-data"
}
```

Priority, lowest → highest: `~/.agent-browser/config.json` < `./agent-browser.json` < env vars < CLI flags. `--config <path>` or `AGENT_BROWSER_CONFIG` selects a custom config; missing/invalid files exit with an error. CLI options map to camelCase keys, e.g. `--executable-path` → `"executablePath"`. Boolean flags accept `true`/`false`, e.g. `--headed false` overrides config. User and project config extensions merge rather than replace.
