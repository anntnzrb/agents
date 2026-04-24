# AGENTS.md

## Layout

- `assets/`: SSOT for agent assets (skills, agents, shared config)
- `tools/`: tool-specific configs staged for sync
- `sync/`: isolated TypeScript sync application; owns all JS/TS app config and dependencies
- Do not directly edit synced tool homes (`~/.codex`, `~/.claude`, etc.); changes must land here to avoid sync overwriting them

## Sync entrypoint

- Public sync entrypoint: `sync/src/cli.ts`
- Invoke it with an explicit Bun runner, e.g. `bun ./sync/src/cli.ts` from repo root
- Do not add `bin/` shell trampolines for sync
- Agent launch wrappers live in `~/repos/rice/nix/modules/home/cli/llm-agents/` and pass pinned Nix Bun + this sync script path explicitly

## Commit format

Prefix subject with tool name:

- `pi: ...`
- `codex: ...`
- `claude: ...`
- `opencode: ...`

For repo-level changes use conventional commits.
