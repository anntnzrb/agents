# Session Management

Multiple isolated browser sessions; state persistence and concurrent browsing supported. Read before using named sessions, saved state, concurrency, or cleanup policies.

## Named Sessions
`--session NAME` isolates browser commands and context state.

```bash
# Session 1: Authentication flow
agent-browser --session auth open https://app.example.com/login

# Session 2: Public browsing (separate cookies, storage)
agent-browser --session public open https://example.com

# Commands are isolated by session
agent-browser --session auth fill @e1 "user@example.com"
agent-browser --session public get text body
```

Each session independently owns:

- Cookies
- LocalStorage / SessionStorage
- IndexedDB
- Cache
- Browsing history
- Open tabs

## State Persistence

```bash
# Save cookies, storage, and auth state
agent-browser state save /path/to/auth-state.json

# Restore saved state
agent-browser state load /path/to/auth-state.json
agent-browser open https://app.example.com/dashboard
```

State files contain cookies, localStorage, sessionStorage, and origins:

```json
{
  "cookies": [...],
  "localStorage": {...},
  "sessionStorage": {...},
  "origins": [...]
}
```

### Authenticated Session Reuse

```bash
# Save login state once, reuse many times

STATE_FILE="<temp-dir>/auth-state.json"

# Check if we have saved state
if [[ -f "$STATE_FILE" ]]; then
    agent-browser state load "$STATE_FILE"
    agent-browser open https://app.example.com/dashboard
else
    # Perform login
    agent-browser open https://app.example.com/login
    agent-browser snapshot -i
    agent-browser fill @e1 "$USERNAME"
    agent-browser fill @e2 "$PASSWORD"
    agent-browser click @e3
    agent-browser wait --load networkidle

    # Save for future use
    agent-browser state save "$STATE_FILE"
fi
```

### Concurrent Scraping

```bash
# Scrape multiple sites concurrently

# Start all sessions
agent-browser --session site1 open https://site1.com &
agent-browser --session site2 open https://site2.com &
agent-browser --session site3 open https://site3.com &
wait

# Extract from each
agent-browser --session site1 get text body > site1.txt
agent-browser --session site2 get text body > site2.txt
agent-browser --session site3 get text body > site3.txt

# Cleanup
agent-browser --session site1 close
agent-browser --session site2 close
agent-browser --session site3 close
```

### A/B Testing

```bash
# Test different user experiences
agent-browser --session variant-a open "https://app.com?variant=a"
agent-browser --session variant-b open "https://app.com?variant=b"

# Compare
agent-browser --session variant-a screenshot <temp-dir>/variant-a.png
agent-browser --session variant-b screenshot <temp-dir>/variant-b.png
```

## Default Session
Omitting `--session` uses the default session; commands without it share that session.

```bash
# These use the same default session
agent-browser open https://example.com
agent-browser snapshot -i
agent-browser close  # Closes default session
```

## Cleanup

```bash
# Close specific session
agent-browser --session auth close

# List active sessions
agent-browser session list
```

## Best Practices

- Name sessions by purpose, not generic names:

  ```bash
  # GOOD: Clear purpose
  agent-browser --session github-auth open https://github.com
  agent-browser --session docs-scrape open https://docs.example.com

  # AVOID: Generic names
  agent-browser --session s1 open https://github.com
  ```
- Close sessions when done:

  ```bash
  # Close sessions when done
  agent-browser --session auth close
  agent-browser --session scrape close
  ```
- Protect state files containing auth tokens; do not commit them, ignore `*.auth-state.json`, and delete temporary state:

  ```bash
  # Don't commit state files (contain auth tokens!)
  echo "*.auth-state.json" >> .gitignore

  # Delete after use
  rm <temp-dir>/auth-state.json
  ```
- Timeout long automated sessions:

  ```bash
  # Set timeout for automated scripts
  timeout 60 agent-browser --session long-task get text body
  ```
