# AGENTS.md

## Scope

- `assets/`: SSOT for agent assets: skills, agents, and shared config.
- `tools/`: tool-specific configs staged for sync.
- `sync/`: isolated TypeScript sync application; owns all JS/TS app config and dependencies.
- Agent config root: `~/.config/agents/`.
- Synced tool homes (`~/.codex`, `~/.claude`, etc.) are generated targets. Make durable changes here so sync does not overwrite them.

## Sync Contract

- Public sync entrypoint: `sync/src/cli.ts`.
- Invoke it with an explicit Bun runner, e.g. `bun ./sync/src/cli.ts` from repo root.
- NEVER add `bin/` shell trampolines for sync.

## Commit Contract

Prefix subject with tool name:

- `pi: ...`
- `codex: ...`
- `claude: ...`
- `opencode: ...`

For repo-level changes, use conventional commits.

<critical>
- NEVER edit generated synced homes unless the user asks and the SSOT impact is clear.
</critical>
