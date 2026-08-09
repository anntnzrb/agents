# Pattern Cookbook

Use these patterns to build robust shortcuts quickly.

Read this when the blueprint needs reusable input, control-flow, or failure-handling patterns.

## Pattern 1: Input Normalization

- Use `Ask for Input` or Share Sheet input
- Convert to expected type early
- Exit with clear error message when type mismatch

## Pattern 2: Guarded API Call

1. Build request URL and headers
2. Validate required token/key exists
3. Call API
4. If response missing expected field, branch to fallback

## Pattern 3: Menu-Driven Branch

- `Choose from Menu` for explicit user path
- One branch per task
- End each branch with uniform output format

## Pattern 4: Retry with Cap

- Repeat N times
- Stop early on success
- Provide final failure notice after max attempts

## Pattern 5: List Pipeline

1. `Find` or `Filter`
2. `Sort`
3. `Repeat with Each`
4. Accumulate output dictionary/list

## Pattern 6: Dictionary Contract

- Define required keys up front
- Populate optional keys conditionally
- Output one stable dictionary object for downstream actions

## Pattern 7: URL Scheme Launcher

- Validate app availability or fallback app
- Encode parameters safely
- Log the final URL in debug mode

## Pattern 8: Cross-Device Safe Output

- Produce plain text + rich output variant
- Default to plain text when target capability uncertain

## Pattern 9: Confirmation Gate

- Show summary before destructive action
- Confirm via menu or alert
- Cancel path must be explicit

## Pattern 10: Debug Toggle

- Use a `debug` variable
- Emit intermediate values only when debug is true
- Keep production output clean
