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
- A supported `../tools/<harness>/` directory opts into that harness; `src/core/harness-adapters.ts` owns internal launch and sync metadata.
- Use layer aliases for cross-boundary imports. Keep same-directory imports relative.
- Sync owns generated launch wrappers: Unix targets live in `~/.local/bin`; Windows targets live in `%LOCALAPPDATA%/Programs/Agents/bin`.
- Unix PATH is assumed to be configured. Windows user PATH is updated at most once and recorded by the durable `windows-path-added` marker.

## Launch Wrapper Contract

- A manual sync creates or reconciles wrappers before returning.
- Generated wrappers call `bun ~/.config/agents/sync/src/cli.ts launch <harness> -- ...`; launch performs a best-effort sync, then resolves and runs the cached npm binary.
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
