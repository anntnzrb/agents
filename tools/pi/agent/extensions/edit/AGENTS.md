# Edit Extension (UI compaction override)

## Purpose
Keep native `edit` execution behavior untouched while reducing UI noise:
- naked single-line edit telemetry
- no expand hint or native expanded diff UI
- successful result renders no extra output
- errors remain visible/actionable
- model-visible tool result stays unchanged

## Files
- `index.ts` — wraps built-in `edit` tool and overrides UI rendering only
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Uses native Pi execute path unchanged (`...createEditToolDefinition(process.cwd())`)
- Preserves model context and edit semantics
- Only UI rendering is overridden
