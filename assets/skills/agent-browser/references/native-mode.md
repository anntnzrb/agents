# Native Mode

Native mode is experimental. It uses a Rust daemon that communicates with Chrome directly via CDP, bypassing Node.js and Playwright. Use it only when explicitly needed; it is not RECOMMENDED for production.

```text
# Enable via flag
agent-browser --native open example.com

# Enable via environment variable (avoids passing --native every time)
export AGENT_BROWSER_NATIVE=1
agent-browser open example.com
```

The native daemon supports Chromium and Safari via WebDriver. Firefox and WebKit are not yet supported. Core commands such as navigate, snapshot, click, fill, screenshot, cookies, storage, tabs, and eval should behave the same as default mode. You MUST run `agent-browser close` before switching between native and default mode within the same session.
