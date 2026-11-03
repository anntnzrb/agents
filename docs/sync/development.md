# Develop the sync application

Sync is a Bun TypeScript application under `sync/`. See the [sync architecture](../../sync/ARCHITECTURE.md) for the Effect design, source layout, and module rules, and [Manage shared skills](../skills.md) for the shared-skill workflow.

## Run sync from source

From the repository root, install dependencies and invoke the public entrypoint:

```bash
bun install --cwd sync --frozen-lockfile
bun run --cwd sync sync
```

Sync reads its sources from `~/src/agents`, not the current directory. From another checkout or worktree, the command runs that checkout's code against `~/src/agents`; its local skill, harness, and tool changes are not published. After the changes merge, each host's [background updater](sync.md#background-updates) fast-forwards the source checkout.

See the [sync reference](sync.md#installed-runtime) for the installed executable.

## Run checks

Run the complete contributor gates from the repository root:

```bash
bun install --cwd sync --frozen-lockfile
bun run --cwd sync gates
```

The `gates` script runs `check`, then `bun test`. The `check` script runs TypeScript type checking (`tsconfig.json`), Effect diagnostics (`effect-tsgo diagnostics`, configured by the `@effect/language-service` plugin in `tsconfig.json`), type-aware Oxlint with the Effect rules (`effect-tsgo oxlint`, configured by `.oxlintrc.json`), and the Oxfmt formatting check (`.oxfmtrc.json`). Those files own every rule and severity; fix findings instead of weakening a rule or adding a suppression. To run static checks alone, use `bun run --cwd sync check`. For an individual gate, use the corresponding script in `sync/package.json`.

To run a focused test, pass its path relative to `sync/`; the `#domain/*`-style imports resolve from `sync/package.json`:

```bash
bun test --cwd sync test/domain/ImportScan.test.ts
bun test --cwd sync test/jobs/Wrappers.test.ts
```

Coverage is diagnostic, not a gate. Do not duplicate process-level scenarios in unit tests to raise coverage.

## Write useful tests

- Add the narrowest regression test that covers the changed sync contract.
- Test one behavior at the lowest layer that observes it. Do not repeat the same scenario in unit and process-level suites.
- Test shared code once, beside the shared module. A consumer test covers only its own wiring.
- Assert observable behavior and contracts, not fixtures, mocks, or implementation details.
- Add a test only when it can fail on a real regression. Delete tests that duplicate coverage.
- Add process-level integration coverage when a change creates a generated target or crosses a runtime boundary. Use harness names and paths as fixtures or adapter boundaries.
- Keep skill and harness tests beside their owning source. `sync/test/` covers sync behavior only.
- Process-tree tests must not race child startup. Publish readiness from the child and gate the cancelling assertion on that signal. Use wall-clock ceilings as hang detectors derived from the configured timeout, not latency budgets. A ceiling below the fixture's own sleep duration must still detect an unenforced timeout.
- Isolate test homes and external services. A temporary home alone does not isolate `systemctl --user` from the host user manager; isolate its runtime directory and D-Bus environment when exercising it.

## Change sync behavior

1. Find the owning module under `sync/src/`.
2. Add or update the focused test and make the smallest implementation change.
3. Run the focused test and the complete contributor gates.
4. Run `git diff --check` from the repository root.
5. Update the related page under `docs/sync/` when commands, paths, lifecycle, platforms, or generated behavior change.

Keep wrapper generation inside sync, make filesystem operations safe to retry, and preserve unmanaged files unless recorded ownership permits cleanup.

## Change harness configuration

1. Edit the matching source under `harnesses/` and run its own validation from its README.
2. Run `bun run --cwd sync sync` from `~/src/agents`.
3. Inspect the generated root derived from the adapter's `homeSegments` and `runtimeSubdir` fields.
4. Run the wrapper with `--version`.
5. Commit as `<harness>: ...` (see the Git Contract in `AGENTS.md`).

Keep harness-specific tests and documentation beside the owning source under `harnesses/`. Do not edit a generated harness home; sync replaces managed files on the next run.

## Add a harness adapter

1. Append the adapter to `HARNESS_ADAPTERS` in `sync/src/domain/HarnessAdapters.ts` and add its source directory under `harnesses/<id>/`.
2. Resolve adapter metadata through `harnessFromAdapter` in `sync/src/domain/Harness.ts`.
3. Add wrapper tests for every supported platform and integration coverage for generated files and hooks.
4. Run the full checks and update the [harness adapter reference](harnesses.md) when the shared workflow or a harness-specific user action changes.

Keep launcher metadata in the adapter. Do not duplicate package names, target homes, hook rules, or the supported-harness roster in user configuration or documentation. Append adapters rather than reordering them: registry order determines discovery and planning order.

## Add a managed tool

Tool sources live under `tools/<tool>/`. Sync reads them from `~/src/agents` and does not publish that directory itself.

- Add an npm launcher to `TOOL_LAUNCHERS` in `sync/src/domain/ToolLaunchers.ts` for a wrapper and versioned cache.
- Add configuration publication jobs in `sync/src/services/Planner.ts`.
- Add maintenance commands to the sync job programs. The machine configuration owns long-running services and their update logic.

Document tool operation on a focused page under `docs/` and link it from `docs/index.md`. Commit tool sources as `tools(<tool>): ...` and sync changes as `sync: ...`.

## Parsing and filesystem contracts

`sync/src/domain/ImportScan.ts` extracts runtime JavaScript and TypeScript imports, including literal dynamic imports and CommonJS `require` calls. Preserve comment and string immunity and type-only import handling; cover adversarial cases in `sync/test/domain/ImportScan.test.ts`. Package validation excludes relative paths, built-in modules, and `data:` URLs.

JSONC input accepts comments and trailing commas. Deployment settings reject unknown fields. Dotenv defaults do not expand variables and omit empty values. Endpoint publication preserves designated TOML tables without rewriting unrelated content.

Preserve deterministic fingerprint bytes and matching destination inode and modification time when changing filesystem work. See the [runtime release id](sync.md#installed-runtime) and the [extension hook fingerprint](sync.md#extension-hook-state).
