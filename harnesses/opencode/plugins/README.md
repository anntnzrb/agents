# OpenCode plugins

## Manual continuation

`tmap/index.ts` uses the OpenCode v2 `context` hook. When the latest user message contains only a single
period, it changes that message to `Continue.` in model-visible context and adds a system-priority
notice to resume unfinished work. The notice also applies to tool-driven continuations until another
user message arrives. Persisted history keeps the original period; v2 does not expose the v1
synthetic/system fields on prompt admission. Messages with attachments are left unchanged.

Both plugins are explicitly configured as directories. The released 2.0.7 loader rejects explicitly
configured `.ts` file paths, even though the migration documentation shows them.

## Validation

From a temporary copy of `harnesses/opencode/` (to avoid installing dependencies into the SSOT):

```sh
bun install
bun test ./tests/plugins.test.ts
bun x --package typescript tsc --noEmit --strict --skipLibCheck --types node \
  --target esnext --module nodenext --moduleResolution nodenext \
  plugins/tmap/index.ts plugins/cliproxy/index.ts
```

Tests exercise the continuation hook and model discovery with mocked HTTP responses, validate model
records against the v2 schema, check transform replay, and preserve inventory on gateway failure.
