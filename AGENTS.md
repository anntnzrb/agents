# AGENTS.md

## Scope

- `assets/`: SSOT for agent assets (skills, agents, shared config)
- `tools/`: tool-specific configs staged for sync
- `sync/`: isolated TypeScript sync application; owns all JS/TS app config and dependencies
- Treat synced tool homes (`~/.codex`, `~/.claude`, etc.) as generated targets. Make durable changes here so sync does not overwrite them.

## Sync Contract

- Public sync entrypoint: `sync/src/cli.ts`
- Invoke it with an explicit Bun runner, e.g. `bun ./sync/src/cli.ts` from repo root.
- Do not add `bin/` shell trampolines for sync; agent launch wrappers live in `~/repos/rice/nix/modules/home/cli/llm-agents/` and call pinned Nix Bun plus this sync script path explicitly.

## Commit Contract

Prefix subject with tool name:

- `pi: ...`
- `codex: ...`
- `claude: ...`
- `opencode: ...`

For repo-level changes use conventional commits.

## Stop Rules

- Stage or commit only when the user explicitly asks.
- Do not edit generated synced homes unless the user asks and the SSOT impact is clear.
