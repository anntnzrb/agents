# AGENTS.md

This holds the stable sync wrapper used to manage and sync these AI Agent configs. Keep changes in the TypeScript sources under `sync/`, not in synced tool homes, because sync will overwrite tool-home copies.

## Full gate

- `./bin/sync`
- `bun run typecheck`
- `bun test`
- `bun run test:integration`
