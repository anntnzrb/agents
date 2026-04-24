# Read Extension (UI compaction override)

## Purpose
Keep native `read` execution behavior untouched while reducing UI noise:
- naked single-line read telemetry
- no expand hint or native expanded content UI
- successful result renders no extra output unless truncated
- errors remain visible/actionable
- model-visible tool result stays unchanged

## Files
- `index.ts` — wraps built-in `read` tool and overrides UI rendering only
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Uses native Pi execute path unchanged (`...createReadToolDefinition(process.cwd())`)
- Preserves model context: full tool output still returned in `content`
- Only UI rendering is overridden
