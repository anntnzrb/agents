# AGENTS.md

## Scope

- `HARNESS.md`: SSOT for global, harness-agnostic agent instructions; sync publishes it to every harness as its instruction file
- `skills/current/`: SSOT for shared skills synced to every harness
- `skills/legacy/`: archived skills; repo-only, not synced
- `tools/`: repo-only managed-tool sources
- `sync/`: isolated Python (uv) sync application; owns all sync configuration, launcher wrappers, dependencies, and `sync/tests/`
- `sync/tests/`: tests sync behavior only; harness names and paths MAY appear as fixtures or adapter boundaries, but tests MUST NOT import harness implementations or assert harness-local behavior; skill and harness changes MUST NOT add tests here
- `docs/`: repository setup, operation, and workflow documentation indexed by `docs/index.md`
- `docs/sync/`: sync application documentation; adapter boundaries MAY be described, but harness-local behavior and configuration belong under `harnesses/`
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

Skills are modified here, in the SSOT. Always run against the skill gate: `./docs/skills.md`

## Documentation Gate

Route documentation by owner:

- Sync application behavior, commands, reconciliation, lifecycle, supported platforms, generated paths, and adapter boundaries: `docs/sync/`.
- Repository setup, operation, and workflow documentation, including the repository layout: `docs/`.
- Behavior or configuration owned entirely by one harness: beside the source under `harnesses/<harness>/`; never in `docs/`.

Boundaries:

- A skill change MUST NOT add tests under `sync/tests/` or documentation under `docs/sync/`. The skill's own files carry its documentation and validation commands.
- A change under `harnesses/` MUST NOT update `docs/` or `sync/tests/`. Adapter-contract changes in `sync/src/sync/core/harness_adapters.py` are sync changes; they follow the sync workflow and MAY update `docs/sync/`.

For changes routed to `docs/`:

1. Read `docs/index.md` and every related page completely; follow their cross-references before editing.
2. Update the relevant existing page in the same change. Create a new focused topic page only when no current page fits.
3. Link new pages from `docs/index.md`.
4. Separate procedures, explanation, and reference with clear headings. Use direct language, concrete paths, and copy-pasteable commands.
5. Derive claims from the implementation and validated behavior. Never document guessed behavior, secrets, local credentials, or generated machine-specific values.
6. Validate links, paths, platform claims, and commands. Run `git diff --check` and the relevant code checks before handoff.

Documentation-only changes must still preserve navigation and factual accuracy. Do not generate filler pages, duplicate existing guidance, or cargo-cult documentation templates.

## Sync Contract

- Public sync entrypoint: `sync/src/sync/cli.py` (`sync` console script)
- Invoke it via `uv`, e.g. `uv run --project sync sync` from repository root
- NEVER add `bin/` shell trampolines for sync
- Use TDD

## Git Contract

Commits: 
- For harness-specific changes use `<harness>: ...`; that is `pi: configure fallback model`
- For generic changes: `docs:`, `sync:`, `skills(<skill>):`
