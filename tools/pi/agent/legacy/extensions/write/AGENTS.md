# Write Extension (native write override)

## Purpose

Keep native `write` behavior close while adding stale-write hardening and reducing UI noise:

- atomic temp-file + rename writes
- optional `expectedHash` stale-write guard
- naked single-line write telemetry
- no expand hint or native expanded call UI
- model-visible success result stays native-shaped

## Files

- `index.ts` — wraps built-in `write`, overrides execution minimally, and overrides UI call rendering
- `tsconfig.json` — strict TS config matching sibling extensions

## Invariants

- Starts from `createWriteToolDefinition(process.cwd())` and preserves native metadata/render result
- Execution stays in Pi's `withFileMutationQueue`
- `expectedHash` is SHA-256 hex over current file bytes; mismatch rejects before writing

## Stop Rules

- Preserve native write behavior except for the documented stale-write guard and UI compaction.
- Do not add unrelated file mutation policy here.
