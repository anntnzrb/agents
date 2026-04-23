# Read Extension (UI compaction override)

## Purpose
Keep native `read` execution behavior untouched while reducing UI noise:
- collapsed mode shows a compact status summary only
- expanded mode (`Ctrl+O`) shows full raw output
- errors remain fully visible
- default boxed tool shell remains unchanged

## Files
- `index.ts` — wraps built-in `read` tool and overrides only collapsed `renderResult`
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Uses native Pi execute path unchanged (`...createReadToolDefinition(process.cwd())`)
- Preserves model context: full tool output still returned in `content`
- Only UI surface is overridden (`renderResult`)
