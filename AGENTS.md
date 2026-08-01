# AGENTS.md

## Scope

- `assets/AGENTS.md`: SSOT for global, harness-agnostic agent instructions
- `assets/skills/`: SSOT for shared skills and skill-scoped policy
- Other `assets/` entries: SSOT for shared agents and configuration
- `tools/`: tool-specific configs staged for sync
- `sync/`: isolated TypeScript sync application; owns all JS/TS app config and dependencies
- Agent config root: `~/.config/agents/`
- Synced tool homes (`~/.codex`, `~/.claude`, etc.) are generated targets
- Make durable changes in this repository so sync does not overwrite them

<critical>
- NEVER edit generated synced homes unless the user asks and the SSOT impact is clear
</critical>

## Sync Contract

- Public sync entrypoint: `sync/src/cli.ts`
- Invoke it with an explicit Bun runner, e.g. `bun ./sync/src/cli.ts` from repo root
- NEVER add `bin/` shell trampolines for sync

## Git Contract

Commits: 
- For harness-specific changes use `<harness>: ...`; that is `pi: configure fallback model`
- For generic changes: `docs:`, `sync:`, `skills(<skill>):`
