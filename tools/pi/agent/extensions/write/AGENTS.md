# Write Extension (UI call compaction override)

## Purpose
Keep native `write` execution behavior untouched while reducing UI noise:
- naked single-line write telemetry
- no expand hint or native expanded call UI
- result/error behavior stays native
- model-visible tool result stays unchanged

## Files
- `index.ts` — wraps built-in `write` tool and overrides UI call rendering only
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Uses native Pi execute path unchanged (`...createWriteToolDefinition(process.cwd())`)
- Preserves model context and write semantics
- Only UI call rendering is overridden
