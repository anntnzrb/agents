# Native Mode

Experimental Rust daemon; direct Chrome CDP; bypasses Node.js and Playwright. Use only when explicitly needed; not RECOMMENDED for production.

```text
# Enable via flag
agent-browser --native open example.com

# Enable via environment variable (avoids passing --native every time)
export AGENT_BROWSER_NATIVE=1
agent-browser open example.com
```

Native daemon supports Chromium and Safari via WebDriver; Firefox and WebKit unsupported. Core commands such as navigate, snapshot, click, fill, screenshot, cookies, storage, tabs, and eval should behave the same as default mode. MUST run `agent-browser close` before switching between native and default mode within the same session.
