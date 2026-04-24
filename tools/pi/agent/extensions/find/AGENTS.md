# Find Extension (Native override + auto-enable)

## Purpose
Keep `find` always active and add low-maintenance ROI features:
- `hidden` toggle
- `path | paths` multipath discovery with dedupe
- deterministic ordering
- `limit+1` probe for accurate truncation notice
- bounded timeout with explicit timeout error
- naked compact UI rendering with max-two-line telemetry

## Files
- `index.ts` — tool override + activation hooks
- `index.test.ts` — pure helper behavior checks
- `index.render.test.ts` — compact rendering checks
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Dynamic activation: preserves existing active tools while forcing `find` on
- Overrides built-in `find` with fd-backed multipath/timeout behavior
- Avoids mtime sort/cache complexity by design
