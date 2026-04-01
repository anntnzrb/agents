# AGENTS.md

## Layout

- `assets/`: SSOT for agent assets (skills, agents, shared config)
- `tools/`: tool-specific configs staged for sync
- `sync/`: isolated TypeScript sync application; owns all JS/TS app config and dependencies
- `bin/sync`: minimal public wrapper for the sync app; keep `bin/` tiny and behavior in `./sync/`
- Do not directly edit synced tool homes (`~/.codex`, `~/.claude`, etc.); changes must land here for sync to overwriting

## Commit format

Prefix subject with tool name:

- `pi: ...`
- `codex: ...`
- `claude: ...`
- `opencode: ...`

For repo-level changes use conventional commits.
