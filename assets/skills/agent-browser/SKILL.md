---
name: agent-browser
description: "Automates browser interactions for web testing, form filling, screenshots, and data extraction. Use when the user needs to navigate websites, interact with web pages, fill forms, take screenshots, test web applications, or extract information from web pages."
---

# Browser Automation with agent-browser

## Quick start

```bash
bun x agent-browser open <url>        # Navigate to page
bun x agent-browser snapshot -i       # Get interactive elements with refs
bun x agent-browser click @e1         # Click element by ref
bun x agent-browser fill @e2 "text"   # Fill input by ref
bun x agent-browser close             # Close browser
```

## Core workflow

1. Navigate: `agent-browser open <url>`
2. Snapshot: `agent-browser snapshot -i` (returns elements with refs like `@e1`, `@e2`)
3. Interact using refs from the snapshot
4. Re-snapshot after navigation or significant DOM changes

## Commands

### Navigation
```bash
bun x agent-browser open <url>      # Navigate to URL
bun x agent-browser back            # Go back
bun x agent-browser forward         # Go forward
bun x agent-browser reload          # Reload page
bun x agent-browser close           # Close browser
```

### Snapshot (page analysis)
```bash
bun x agent-browser snapshot            # Full accessibility tree
bun x agent-browser snapshot -i         # Interactive elements only (recommended)
bun x agent-browser snapshot -c         # Compact output
bun x agent-browser snapshot -d 3       # Limit depth to 3
bun x agent-browser snapshot -s "#main" # Scope to CSS selector
```

### Interactions (use @refs from snapshot)
```bash
bun x agent-browser click @e1           # Click
bun x agent-browser dblclick @e1        # Double-click
bun x agent-browser focus @e1           # Focus element
bun x agent-browser fill @e2 "text"     # Clear and type
bun x agent-browser type @e2 "text"     # Type without clearing
bun x agent-browser press Enter         # Press key
bun x agent-browser press Control+a     # Key combination
bun x agent-browser keydown Shift       # Hold key down
bun x agent-browser keyup Shift         # Release key
bun x agent-browser hover @e1           # Hover
bun x agent-browser check @e1           # Check checkbox
bun x agent-browser uncheck @e1         # Uncheck checkbox
bun x agent-browser select @e1 "value"  # Select dropdown
bun x agent-browser scroll down 500     # Scroll page
bun x agent-browser scrollintoview @e1  # Scroll element into view
bun x agent-browser drag @e1 @e2        # Drag and drop
bun x agent-browser upload @e1 file.pdf # Upload files
```

### Get information
```bash
bun x agent-browser get text @e1        # Get element text
bun x agent-browser get html @e1        # Get innerHTML
bun x agent-browser get value @e1       # Get input value
bun x agent-browser get attr @e1 href   # Get attribute
bun x agent-browser get title           # Get page title
bun x agent-browser get url             # Get current URL
bun x agent-browser get count ".item"   # Count matching elements
bun x agent-browser get box @e1         # Get bounding box
```

### Check state
```bash
bun x agent-browser is visible @e1      # Check if visible
bun x agent-browser is enabled @e1      # Check if enabled
bun x agent-browser is checked @e1      # Check if checked
```

### Screenshots & PDF
```bash
bun x agent-browser screenshot          # Screenshot to stdout
bun x agent-browser screenshot path.png # Save to file
bun x agent-browser screenshot --full   # Full page
bun x agent-browser pdf output.pdf      # Save as PDF
```

### Video recording
```bash
bun x agent-browser record start ./demo.webm    # Start recording (uses current URL + state)
bun x agent-browser click @e1                   # Perform actions
bun x agent-browser record stop                 # Stop and save video
bun x agent-browser record restart ./take2.webm # Stop current + start new recording
```
Recording creates a fresh context but preserves cookies/storage from your session. If no URL is provided, it automatically returns to your current page. For smooth demos, explore first, then start recording.

### Wait
```bash
bun x agent-browser wait @e1                     # Wait for element
bun x agent-browser wait 2000                    # Wait milliseconds
bun x agent-browser wait --text "Success"        # Wait for text
bun x agent-browser wait --url "**/dashboard"    # Wait for URL pattern
bun x agent-browser wait --load networkidle      # Wait for network idle
bun x agent-browser wait --fn "window.ready"     # Wait for JS condition
```

### Mouse control
```bash
bun x agent-browser mouse move 100 200      # Move mouse
bun x agent-browser mouse down left         # Press button
bun x agent-browser mouse up left           # Release button
bun x agent-browser mouse wheel 100         # Scroll wheel
```

### Semantic locators (alternative to refs)
```bash
bun x agent-browser find role button click --name "Submit"
bun x agent-browser find text "Sign In" click
bun x agent-browser find label "Email" fill "user@test.com"
bun x agent-browser find first ".item" click
bun x agent-browser find nth 2 "a" text
```

### Browser settings
```bash
bun x agent-browser set viewport 1920 1080      # Set viewport size
bun x agent-browser set device "iPhone 14"      # Emulate device
bun x agent-browser set geo 37.7749 -122.4194   # Set geolocation
bun x agent-browser set offline on              # Toggle offline mode
bun x agent-browser set headers '{"X-Key":"v"}' # Extra HTTP headers
bun x agent-browser set credentials user pass   # HTTP basic auth
bun x agent-browser set media dark              # Emulate color scheme
```

### Cookies & Storage
```bash
bun x agent-browser cookies                     # Get all cookies
bun x agent-browser cookies set name value      # Set cookie
bun x agent-browser cookies clear               # Clear cookies
bun x agent-browser storage local               # Get all localStorage
bun x agent-browser storage local key           # Get specific key
bun x agent-browser storage local set k v       # Set value
bun x agent-browser storage local clear         # Clear all
```

### Network
```bash
bun x agent-browser network route <url>              # Intercept requests
bun x agent-browser network route <url> --abort      # Block requests
bun x agent-browser network route <url> --body '{}'  # Mock response
bun x agent-browser network unroute [url]            # Remove routes
bun x agent-browser network requests                 # View tracked requests
bun x agent-browser network requests --filter api    # Filter requests
```

### Tabs & Windows
```bash
bun x agent-browser tab                 # List tabs
bun x agent-browser tab new [url]       # New tab
bun x agent-browser tab 2               # Switch to tab
bun x agent-browser tab close           # Close tab
bun x agent-browser window new          # New window
```

### Frames
```bash
bun x agent-browser frame "#iframe"     # Switch to iframe
bun x agent-browser frame main          # Back to main frame
```

### Dialogs
```bash
bun x agent-browser dialog accept [text]  # Accept dialog
bun x agent-browser dialog dismiss        # Dismiss dialog
```

### JavaScript
```bash
bun x agent-browser eval "document.title"   # Run JavaScript
```

## Example: Form submission

```bash
bun x agent-browser open https://example.com/form
bun x agent-browser snapshot -i
# Output shows: textbox "Email" [ref=e1], textbox "Password" [ref=e2], button "Submit" [ref=e3]

bun x agent-browser fill @e1 "user@example.com"
bun x agent-browser fill @e2 "password123"
bun x agent-browser click @e3
bun x agent-browser wait --load networkidle
bun x agent-browser snapshot -i  # Check result
```

## Example: Authentication with saved state

```bash
# Login once
bun x agent-browser open https://app.example.com/login
bun x agent-browser snapshot -i
bun x agent-browser fill @e1 "username"
bun x agent-browser fill @e2 "password"
bun x agent-browser click @e3
bun x agent-browser wait --url "**/dashboard"
bun x agent-browser state save auth.json

# Later sessions: load saved state
bun x agent-browser state load auth.json
bun x agent-browser open https://app.example.com/dashboard
```

## Sessions (parallel browsers)

```bash
bun x agent-browser --session test1 open site-a.com
bun x agent-browser --session test2 open site-b.com
bun x agent-browser session list
```

## JSON output (for parsing)

Add `--json` for machine-readable output:
```bash
bun x agent-browser snapshot -i --json
bun x agent-browser get text @e1 --json
```

## Debugging

```bash
bun x agent-browser open example.com --headed              # Show browser window
bun x agent-browser console                                # View console messages
bun x agent-browser errors                                 # View page errors
bun x agent-browser record start ./debug.webm   # Record from current page
bun x agent-browser record stop                            # Save recording
bun x agent-browser open example.com --headed  # Show browser window
bun x agent-browser --cdp 9222 snapshot        # Connect via CDP
bun x agent-browser console                    # View console messages
bun x agent-browser console --clear            # Clear console
bun x agent-browser errors                     # View page errors
bun x agent-browser errors --clear             # Clear errors
bun x agent-browser highlight @e1              # Highlight element
bun x agent-browser trace start                # Start recording trace
bun x agent-browser trace stop trace.zip       # Stop and save trace
```
