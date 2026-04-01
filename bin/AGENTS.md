# AGENTS.md

This holds the minimal public sync wrapper.
Keep `bin/` tiny.
Keep sync behavior and implementation in the repo-root `./sync/` app.

## Full gate

Run from repo root:
- `./bin/sync`
- `cd ./sync && bun run typecheck`
- `cd ./sync && bun test`
- `cd ./sync && bun run test:integration`
