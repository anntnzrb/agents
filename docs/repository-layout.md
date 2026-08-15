# Repository layout

The repository separates committed sources, generated targets, and runtime state.

| Path | Purpose |
|---|---|
| `assets/` | Shared instructions and standalone configuration sources |
| `skills/current/` | Shared skills synced to every harness |
| `skills/legacy/` | Archived skills that sync does not publish |
| `tools/<harness>/` | Harness-specific source configuration |
| `sync/` | Bun and TypeScript reconciliation application |
| `docs/` | Repository documentation |
| `secrets.local.json` | Ignored machine-local secret values |

## Source directories

### `assets/`

`assets/AGENTS.md` is the global instruction source. Sync renames or copies shared assets according to each harness adapter.

Standalone files include:

- `mcporter.jsonc` for MCPorter;
- `cliproxyapi.yaml.tmpl` for CLIProxyAPI;
- `cliproxyapi.release.json` for the pinned release and checksums;
- `skills-gate.md` for skill policy.

### `tools/`

A known directory under `tools/` opts into its adapter in `sync/src/core/harness-adapters.ts`. Pi and OMP use an `agent/` runtime subdirectory. Codex and OpenCode sync directly from their tool directory.

### `sync/`

The sync application owns copies, cleanup, package caches, managed release binaries, and launch wrappers. Its public entrypoint is `sync/src/cli.ts`.

## Generated targets

Generated targets include:

- `~/.codex`;
- `~/.config/opencode`;
- `~/.pi/agent`;
- `~/.omp/agent`;
- `~/.mcporter/mcporter.json`;
- `~/.cli-proxy-api/config.yaml`;
- `~/.local/bin` on macOS and Linux.

Do not edit generated targets. Sync replaces managed content from the committed sources.

## Runtime state

Credentials, sessions, logs, OAuth files, databases, and caches remain outside the repository. Sync preserves runtime state unless a subsystem explicitly owns the path.
