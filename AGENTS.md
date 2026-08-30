# AGENTS.md

## Scope

- `HARNESS.md`: SSOT for global, harness-agnostic agent instructions; sync publishes it to every harness as its instruction file
- `skills/current/`: SSOT for shared skills synced to every harness
- `skills/legacy/`: archived skills; repo-only, not synced
- `tools/`: repo-only managed-tool sources
- `sync/`: native Rust sync application; owns the Cargo workspace, reconciliation engine, launcher wrappers, and runtime integration
- `docs/`: repository setup, operation, and workflow documentation indexed by `docs/index.md`
- `docs/sync/`: sync application documentation; adapter boundaries MAY be described, but harness-local behavior and configuration belong under `harnesses/`
- Harness-specific tests and documentation stay beside their owning source under `harnesses/`
- `harnesses/<harness>/`: directory presence opts into a supported harness; sync owns its internal adapter metadata
- Agent config root: `~/.config/agents/`
- Agentium data root: `~/.local/share/agentium/`
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

- A skill change MUST NOT add tests under `sync/` or documentation under `docs/sync/`. The skill's own files carry its documentation and validation commands.
- A change under `harnesses/` MUST NOT update `docs/` or tests under `sync/`. Adapter-contract changes in `sync/crates/app-core/src/harness_adapters.rs` are sync changes; they follow the sync workflow and MAY update `docs/sync/`.

For changes routed to `docs/`:

1. Read `docs/index.md` and every related page completely; follow their cross-references before editing.
2. Update the relevant existing page in the same change. Create a new focused topic page only when no current page fits.
3. Link new pages from `docs/index.md`.
4. Separate procedures, explanation, and reference with clear headings. Use direct language, concrete paths, and copy-pasteable commands.
5. Derive claims from the implementation and validated behavior. Never document guessed behavior, secrets, local credentials, or generated machine-specific values.
6. Validate links, paths, platform claims, and commands. Run `git diff --check` and the relevant code checks before handoff.

Documentation-only changes must still preserve navigation and factual accuracy. Do not generate filler pages, duplicate existing guidance, or cargo-cult documentation templates.

## Execution model

- Every normal execution MUST use the locally installed native `agentium` binary through the generated wrapper.
- The release artifact MUST consume the host's current harness and configuration inputs. Changes to those inputs MUST NOT require rebuilding or republishing the synchronization application.
- The synchronization engine is a standalone native executable. It MAY invoke Bun only for harness package and extension dependency boundaries. It MUST NOT invoke development tooling or the `npm`, `git`, `gh`, `tar`, or `uv` executables for its own orchestration.

## Sync Contract

- Source workspace: `sync/`
- Development and operational entrypoint: `sync/crates/app/src/main.rs`
- Build with `cargo build --manifest-path sync/Cargo.toml --package app`
- Run the CLI with `cargo run --manifest-path sync/Cargo.toml --package app --`
- NEVER add `bin/` shell trampolines for sync
- Use TDD

## Git Contract

Commits: 
- For harness-specific changes use `<harness>: ...`; that is `pi: configure fallback model`
- For generic changes: `docs:`, `sync:`, `skills(<skill>):`
