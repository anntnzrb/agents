# Pattern Cookbook

Reusable robust-shortcut patterns:

1. Input normalization
- Input: `Ask for Input` or Share Sheet.
- Convert to expected type early; type mismatch → clear error and exit.

2. Guarded API call
- Build request URL/headers; validate required token/key exists; call API.
- Missing expected response field → fallback branch.

3. Menu-driven branch
- `Choose from Menu` → explicit user path; one branch per task; uniform output format per branch.

4. Retry with cap
- Repeat N times; success → stop early; after max attempts → final failure notice.

5. List pipeline
`Find`/`Filter` → `Sort` → `Repeat with Each` → accumulate output dictionary/list.

6. Dictionary contract
- Define required keys upfront; conditionally populate optional keys; output one stable dictionary object for downstream actions.

7. URL scheme launcher
- Validate app availability or fallback app; safely encode parameters; debug mode → log final URL.

8. Cross-device safe output
- Produce plain-text and rich-output variants; uncertain target capability → default to plain text.

9. Confirmation gate
- Before destructive action, show summary; confirm via menu/alert; explicit cancel path required.

10. Debug toggle
- Use a `debug` variable; debug true → emit intermediate values; keep production output clean.
