# Write Extension (UI call compaction override)

## Purpose
Keep native `write` execution behavior untouched while reducing call-preview noise:
- collapsed mode shows compact write summary only
- expanded mode (`Ctrl+O`) shows native full call preview
- result/error behavior stays native
- default boxed tool shell remains unchanged

## Files
- `index.ts` — wraps built-in `write` tool and overrides only collapsed `renderCall`
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Uses native Pi execute path unchanged (`...createWriteToolDefinition(process.cwd())`)
- Preserves model context and write semantics
- Only UI surface is overridden (`renderCall`)
