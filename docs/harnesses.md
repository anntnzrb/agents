# Harnesses

Sync supports Codex, OpenCode, Pi, and OMP. A matching source directory under `harnesses/` opts into the harness.

| Harness | Source | Generated target |
|---|---|---|
| Codex | `harnesses/codex/` | `~/.codex/` |
| OpenCode | `harnesses/opencode/` | `~/.config/opencode/` |
| Pi | `harnesses/pi/agent/` | `~/.pi/agent/` |
| OMP | `harnesses/omp/agent/` | `~/.omp/agent/` |

## Change harness configuration

1. Edit the matching path under `harnesses/`.
2. Run `bun ./sync/src/cli.ts`.
3. Inspect the generated target.
4. Run the harness-specific smoke test.

Do not edit generated tool homes. A later sync replaces managed files.

## Launch wrappers

Sync writes harness commands to `~/.local/bin` on macOS and Linux. On Windows, it writes commands under `%LOCALAPPDATA%/Programs/Agents/bin` and adds that directory to the user path once.

Each wrapper runs sync before it resolves and launches the cached npm package. The cache keeps the current and previous known-good package versions.

## Add a harness

Add an adapter to `sync/src/core/harness-adapters.ts`, create its source directory under `harnesses/`, and add wrapper and integration tests. Keep launcher metadata in the adapter instead of repeating it in user configuration.
