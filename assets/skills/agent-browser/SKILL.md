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

## Required follow-up reads

Read references only when the task crosses the trigger below. Keep this file as the default path for routine open/snapshot/interact/capture work.

| Reference                          | Read when                                                                                                                                                                                  |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `references/commands.md`           | You need an option not shown here, exact CLI syntax, JSON output shape, downloads, cookies/storage, tabs, or command-specific flags.                                                       |
| `references/common-patterns.md`    | You need form submission, auth/state/session examples, data extraction, parallel sessions, CDP attachment, color scheme, visual browser, local file, or iOS Simulator examples.            |
| `references/snapshot-refs.md`      | You will reuse element refs across changing DOM state, debug stale refs, use scoped snapshots, or need cursor-interactive element handling.                                                |
| `references/session-management.md` | You need named sessions, concurrent browser contexts, persistent cookies/localStorage, state files, or cleanup/TTL behavior.                                                               |
| `references/authentication.md`     | The task includes login, OAuth, 2FA, saved credentials, auth vault operations, or state reuse after authentication.                                                                        |
| `references/video-recording.md`    | You need to record a headed/headless run for debugging, evidence, or documentation.                                                                                                        |
| `references/profiling.md`          | You need Chrome DevTools traces, performance profiling, or timing diagnosis.                                                                                                               |
| `references/proxy-support.md`      | You need proxy setup, geo-testing, proxy authentication, or rotating proxies.                                                                                                              |
| `references/advanced.md`           | You need content boundaries, allowlists, action policy, output limits, diffing, timeout strategy, semantic locators, `eval`, persistent config, or advanced ref lifecycle troubleshooting. |
| `references/native-mode.md`        | You need the experimental Rust daemon/native mode, Chromium/Safari WebDriver notes, or native/default switching rules.                                                                     |

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
agent-browser open https://example.com && agent-browser wait --load networkidle && agent-browser snapshot -i
agent-browser fill @e1 "user@example.com" && agent-browser fill @e2 "password123" && agent-browser click @e3
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
agent-browser fill @e2 "text"         # Clear and type text
agent-browser type @e2 "text"         # Type without clearing
agent-browser select @e1 "option"     # Select dropdown option
agent-browser check @e1               # Check checkbox
agent-browser press Enter             # Press key
agent-browser scroll down 500         # Scroll page

# Get information
agent-browser get text @e1            # Get element text
agent-browser get url                 # Get current URL
agent-browser get title               # Get page title

# Wait
agent-browser wait @e1                # Wait for element
agent-browser wait --load networkidle # Wait for network idle
agent-browser wait --url "**/page"    # Wait for URL pattern
agent-browser wait 2000               # Wait milliseconds

# Capture
agent-browser screenshot              # Screenshot to temp dir
agent-browser screenshot --full       # Full page screenshot
agent-browser screenshot --annotate   # Annotated screenshot with numbered element labels
agent-browser pdf output.pdf          # Save as PDF
```

For downloads, tabs/windows, cookies/storage, network, dialogs, JavaScript, global options, debugging commands, and full flag lists, read `references/commands.md`.

## Common Patterns

Read `references/common-patterns.md` when you need complete examples for:

- form submission;
- auth vault and state persistence;
- session persistence and parallel sessions;
- data extraction and JSON output;
- connecting to existing Chrome/CDP;
- color scheme, headed visual browser, local files;
- iOS Simulator/Mobile Safari workflows.

## Advanced Workflows

Read `references/advanced.md` only when you need content boundaries, allowlists, action policy, output limits, snapshot/screenshot diffing, timeout strategy, ref lifecycle troubleshooting, semantic locators, `eval`, or persistent config behavior.

## Experimental: Native Mode

Native mode is experimental and not RECOMMENDED for production. Read `references/native-mode.md` before using `--native` or `AGENT_BROWSER_NATIVE=1`, and always run `agent-browser close` before switching between native and default mode within the same session.

<critical>
At task end, close the browser with `uv run --script <skill-dir>/scripts/cli.py close`. If any browser command output changes the page, invalidates refs, or raises state uncertainty, re-enter the workflow from snapshot or open rather than guessing.
</critical>
