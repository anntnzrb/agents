# AGENTS.md

This is the isolated sync application.

## Scope

- `./package.json`: sync app scripts and dependencies
- `./tsconfig.json`: sync app TypeScript config
- `./bun.lock`: sync app lockfile
- `./biome.jsonc`: sync-scoped formatting, linting, and import organization
- `./.oxlintrc.jsonc`: sync-scoped semantic and type-aware linting
- `./src/`: application code
- `./test/`: sync-specific tests

## Contracts

- Keep behavior changes deliberate.
- Public callable entrypoint is `src/cli.ts`; wrappers/tooling invoke it with an explicit Bun runner.
- Sync supports macOS and Linux only.
- A supported `../harnesses/<harness>/` directory opts into that harness; `src/core/harness-adapters.ts` owns internal launch and sync metadata.
- Use layer aliases for cross-boundary imports. Keep same-directory imports relative.
- Sync owns generated launch wrappers under `~/.local/bin` and assumes that directory is on `PATH`.

## Managed Tool Contract

- Managed release manifests live under `../assets/cliproxyapi/` and pin every supported platform asset by SHA-256.
- Sync downloads only pinned official release assets and caches verified executables under `~/.cache/github-tools` by default.
- Managed tool wrappers use the upstream executable name and pass generated configuration explicitly.
- Sync does not install or control system services.

## Model Catalog Contract

- The normalized model catalog and its cache are harness-agnostic.
- Prefer each harness's native remote-model discovery over generated per-harness catalogs.
- Do not add per-harness model serializers or a `src/harnesses/` materialization layer.
- Live provider catalogs decide availability; models.dev supplies metadata and protocol hints.

## Launch Wrapper Contract

- A manual sync creates or reconciles wrappers before returning.
- Sync installs its runtime under `~/.local/share/agents/sync/`.
- Generated wrappers call `bun ~/.local/share/agents/sync/src/cli.ts launch <harness> -- ...`; launch performs a best-effort sync when the SSOT is available, then resolves and runs the cached npm binary.
- Runtime consumers must read installed state under `~/.local/share/agents/`, not files under the SSOT.
- Launch-time sync failures are warnings; cached harness launch remains available.
- Wrapper ownership is marker- and state-based. Stale generated wrappers are removed only when still owned; unmanaged conflicts are preserved.
- npm launch cache layout is `~/.cache/npm-tools/<tool>/packages/<package-key>/`, with version installs under `versions/<version>/` and package-local `current`/`previous` links.

## Validation

Run from repo root when sync code or tests change:

- `bun ./sync/src/cli.ts`
- `cd ./sync && bun run check`
- `cd ./sync && bun run typecheck`
- `cd ./sync && bun test`
- `cd ./sync && bun run test:integration`

## Stop Rules

- For docs-only edits, skip sync execution unless invocation behavior changed.
- Keep launch-wrapper behavior in this sync app; do not add a second launcher implementation in Rice.
