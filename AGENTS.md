# AGENTS.md

## Layout

- `assets/`: SSOT for agent assets (skills, agents, shared config)
- `tools/`: tool-specific configs staged for sync
- `sync/`: isolated TypeScript sync application
- `bin/sync`: stable sync wrapper for all tool homes
- Do not directly edit synced tool homes (`~/.codex`, `~/.claude`, etc.); changes must land here for sync to overwriting

## Commit format

Prefix subject with tool name:

- `pi: ...`
- `codex: ...`
- `claude: ...`
- `opencode: ...`

For repo-level changes use conventional commits.
