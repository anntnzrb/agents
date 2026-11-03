# AGENTS.md

This is the sync application. See [sync architecture](ARCHITECTURE.md) and [development](../docs/sync/development.md) for layout, conventions, and procedures.

## Scope

- `package.json` and `bun.lock`: application dependencies and contributor commands
- `src/`: application code
- `test/`: sync-specific tests
- `../docs/sync/`: sync application documentation

## Contracts

- Keep behavior changes deliberate. Use TDD.
- The public entrypoint is `src/main.ts`; run it as documented in [development](../docs/sync/development.md#run-sync-from-source).
- Sync supports macOS and Linux only.
- A supported `../harnesses/<harness>/` directory opts into that harness; `src/domain/HarnessAdapters.ts` owns its adapter metadata.
- Follow the module rules in [ARCHITECTURE.md](ARCHITECTURE.md).
- Sync owns generated launch wrappers under `~/.local/bin` and assumes that directory is on `PATH`.

## Managed Tool Contract

- Sync downloads pinned official release assets and caches verified executables.
- Managed tool wrappers use the upstream executable name and pass generated configuration explicitly.
- The machine configuration owns services and timers; sync implements maintenance subcommands (`sync job`).

## Model Catalog Contract

- The normalized model catalog and its cache are harness-agnostic.
- Prefer each harness's native remote-model discovery over generated per-harness catalogs.
- Do not add per-harness model serializers or a per-harness materialization layer.
- Live provider catalogs decide availability; models.dev supplies metadata and protocol hints.

## Launch Wrapper Contract

- A manual sync creates or reconciles wrappers before returning.
- Sync installs its runtime and generates wrappers as described in the [sync reference](../docs/sync/sync.md#installed-runtime). A valid cached package launches immediately; a cold launch performs best-effort sync and blocking package preparation before replacing itself with the harness.
- Runtime consumers read installed state under `~/.local/share/agents/`, not files under the SSOT.
- Cold-launch sync failures are warnings; package preparation still runs. Cached launches skip sync, so managed SSOT edits require manual sync or a scheduled update reconciliation.
- Wrapper ownership is marker- and state-based. Stale generated wrappers are removed only when still owned; unmanaged conflicts are preserved.

## Validation

From `sync/`, run `bun run check` for static checks, `bun test` for tests, or `bun run gates` for both. Git hooks are described in [Git hooks](../.githooks/README.md).

### Code Quality and Typing Policies

- Fix underlying problems rather than weakening gates or adding unjustified suppressions.
- Keep tests deterministic, isolated, and focused on observable contracts.

## Stop Rules

- For docs-only edits, skip sync execution unless invocation behavior changed.
- Keep launch-wrapper behavior in this sync app; do not add a second launcher implementation in Rice.
