# AGENTS.md

## Scope

- `assets/AGENTS.md`: SSOT for global, harness-agnostic agent instructions
- `assets/skills-gate.md`: SSOT for skill-scoped policy; repo-only, not synced
- `assets/cliproxyapi/`: repo-only CLIProxyAPI sources; not synced to harness homes
- `skills/current/`: SSOT for shared skills synced to every harness
- `skills/legacy/`: archived skills; repo-only, not synced
- Other `assets/` entries: SSOT for shared agents and configuration
- `harnesses/`: harness-specific configs, implementations, adjacent tests, and local documentation staged for sync
- `sync/`: isolated TypeScript sync application; owns all JS/TS app config, launcher wrappers, dependencies, and `sync/test/`
- `sync/test/`: tests sync behavior only; harness names and paths MAY appear as fixtures or adapter boundaries, but tests MUST NOT import harness implementations or assert harness-local behavior
- `docs/`: sync application and repository-sync workflow documentation; adapter boundaries MAY be described, but harness-local behavior and configuration belong under `harnesses/`
- Harness-specific tests and documentation stay beside their owning source under `harnesses/`
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

Route documentation by owner:

- For sync application behavior, setup, configuration, lifecycle, supported platforms, commands, generated paths, repository structure, and adapter boundaries, use `docs/`.
- For behavior or configuration owned entirely by one harness, keep documentation beside the source under `harnesses/<harness>/`; do not add it to `docs/`.

For changes routed to `docs/`:

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
