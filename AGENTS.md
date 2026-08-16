# AGENTS.md

## Scope

- `assets/AGENTS.md`: SSOT for global, harness-agnostic agent instructions
- `assets/skills-gate.md`: SSOT for skill-scoped policy; repo-only, not synced
- `assets/cliproxyapi/`: repo-only CLIProxyAPI sources; not synced to harness homes
- `skills/current/`: SSOT for shared skills synced to every harness
- `skills/legacy/`: archived skills; repo-only, not synced
- Other `assets/` entries: SSOT for shared agents and configuration
- `harnesses/`: harness-specific configs staged for sync
- `sync/`: isolated TypeScript sync application; owns all JS/TS app config, launcher wrappers, and dependencies
- `docs/`: SSOT for repository documentation; flat, topic-based pages indexed by `docs/index.md`
- `harnesses/<harness>/`: directory presence opts into a supported harness; sync owns its internal adapter metadata
- Agent config root: `~/.config/agents/`
- Installed runtime root: `~/.local/share/agents/`
- Synced tool homes (`~/.codex`, `~/.claude`, etc.) and agent launch wrappers are generated targets
- Make durable changes in this repository so sync does not overwrite them

<critical>
- NEVER edit generated synced homes unless the user asks and the SSOT impact is clear
- Only sync may read the SSOT directly; wrappers, harnesses, and runtime adapters must use installed state
</critical>

## Skills

Skills are modified here, in the SSOT. Always run against skill gate: `./assets/skills-gate.md`

## Documentation Gate

For changes that affect user-visible behavior, setup, configuration, lifecycle, supported platforms, commands, generated paths, or repository structure:

1. Read `docs/index.md` and every related page completely; follow their cross-references before editing.
2. Update the relevant existing page in the same change. Create a new focused topic page only when no current page fits.
3. Link new pages from `docs/index.md`.
4. Separate procedures, explanation, and reference with clear headings. Use direct language, concrete paths, and copy-pasteable commands.
5. Derive claims from the implementation and validated behavior. Never document guessed behavior, secrets, local credentials, or generated machine-specific values.
6. Validate links, paths, platform claims, and commands. Run `git diff --check` and the relevant code checks before handoff.

Documentation-only changes must still preserve navigation and factual accuracy. Do not generate filler pages, duplicate existing guidance, or cargo-cult documentation templates.

## Sync Contract

- Public sync entrypoint: `sync/src/cli.ts`
- Invoke it with an explicit Bun runner, e.g. `bun ./sync/src/cli.ts` from repo root
- NEVER add `bin/` shell trampolines for sync
- Use TDD

## Git Contract

Commits: 
- For harness-specific changes use `<harness>: ...`; that is `pi: configure fallback model`
- For generic changes: `docs:`, `sync:`, `skills(<skill>):`
