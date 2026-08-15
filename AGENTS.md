# AGENTS.md

## Scope

- `assets/AGENTS.md`: SSOT for global, harness-agnostic agent instructions
- `assets/skills-gate.md`: SSOT for skill-scoped policy; repo-only, not synced
- `skills/current/`: SSOT for shared skills synced to every harness
- `skills/legacy/`: archived skills; repo-only, not synced
- Other `assets/` entries: SSOT for shared agents and configuration
- `tools/`: tool-specific configs staged for sync
- `sync/`: isolated TypeScript sync application; owns all JS/TS app config, launcher wrappers, and dependencies
- `harnesses.ts`: typed root harness catalog; sync and generated launchers consume this declaration directly
- Agent config root: `~/.config/agents/`
- Synced tool homes (`~/.codex`, `~/.claude`, etc.) and agent launch wrappers are generated targets
- Make durable changes in this repository so sync does not overwrite them

<critical>
- NEVER edit generated synced homes unless the user asks and the SSOT impact is clear
</critical>

## Skills

Skills are modified here, in the SSOT. Always run against skill gate: `./assets/skills-gate.md`

## Sync Contract

- Public sync entrypoint: `sync/src/cli.ts`
- Invoke it with an explicit Bun runner, e.g. `bun ./sync/src/cli.ts` from repo root
- NEVER add `bin/` shell trampolines for sync

## Git Contract

Commits: 
- For harness-specific changes use `<harness>: ...`; that is `pi: configure fallback model`
- For generic changes: `docs:`, `sync:`, `skills(<skill>):`
