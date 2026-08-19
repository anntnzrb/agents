# Repository layout

The repository separates committed sources, local inputs, generated targets, and runtime state.

## Committed sources

| Path | Contents |
| --- | --- |
| `AGENTS.md` | Repository policy for contributors and agents |
| `HARNESS.md` | Global harness-independent agent instructions; sync publishes it to every harness as its instruction file |
| `skills/current/` | Shared skills published to enabled harnesses |
| `skills/legacy/` | Archived skills excluded from sync |
| `harnesses/<harness>/` | Harness-owned configuration, implementation, adjacent tests, and local documentation |
| `tools/` | Managed-tool sources: CLIProxyAPI configuration and release manifest, MCPorter configuration |
| `sync/` | The Bun and TypeScript sync application |
| `docs/` | Repository workflow documentation indexed by `docs/index.md`; sync application documentation under `docs/sync/` |
| `secrets.local.example.json` | Schema and placeholder values for local CLIProxyAPI secrets |

### Tool sources

| Path | Purpose |
| --- | --- |
| `tools/cliproxyapi/config.yaml.tmpl` | CLIProxyAPI configuration template and model-source declarations |
| `tools/cliproxyapi/deployment.json` | CLIProxyAPI listener and client endpoint values |
| `tools/cliproxyapi/release.json` | Pinned release assets and SHA-256 checksums |
| `tools/cliproxyapi/panel.html` | Pinned management panel asset |
| `tools/cliproxyapi/panel.patch` | Management panel patch source |
| `tools/cliproxyapi/panel.rebuild.sh` | Management panel rebuild script |
| `tools/mcporter/mcporter.jsonc` | MCPorter configuration source; rendered to `~/.mcporter/mcporter.json` |

### Harness sources

Each harness source starts under `harnesses/<id>/`. When an adapter defines `runtimeSubdir`, sync appends that subdirectory to the source root. Directories outside that root, such as `harnesses/pi/legacy/`, stay repo-only and are never synced.

`sync/src/core/harness-adapters.ts` defines the supported harness IDs, package launchers, generated homes, platforms, runtime subdirectories, and hooks. A matching directory under `harnesses/` enables that adapter on a supported platform.

### Sync application

| Path | Purpose |
| --- | --- |
| `sync/src/cli.ts` | Public command entrypoint |
| `sync/src/core/` | Plans, jobs, adapters, wrappers, managed tools, and model catalogs |
| `sync/src/extensions/` | Extension dependency hooks |
| `sync/src/packages/` | Harness package bootstrap logic |
| `sync/src/runtime/` | Filesystem, process, lock, and error boundaries |
| `sync/test/` | Unit and process-level integration tests for sync behavior |

## Local inputs

`secrets.local.json` contains host-local CLIProxyAPI credentials. The repository ignores it. Create it from `secrets.local.example.json` and keep it outside Git.

## Generated targets

For each harness, `homeSegments` defines the generated harness home. When the adapter defines `runtimeSubdir`, sync appends that subdirectory to the generated root.

Other jobs use fixed generated targets:

| Path | Owner |
| --- | --- |
| `~/.mcporter/mcporter.json` | MCPorter job |
| `~/.cli-proxy-api/config.yaml` | CLIProxyAPI configuration job |
| `~/.local/share/agents/sync/` | Installed sync runtime |
| `~/.local/share/agents/model-catalog/catalog.json` | Shared model-catalog job |
| `~/.local/share/agents/sync-managed/` | Managed ownership and hook state |
| `~/.local/bin/` | Harness and managed-tool wrappers |

Sync replaces managed content in these targets. Make durable changes in the matching committed source.

## Runtime state

Credentials, OAuth files, sessions, logs, databases, and HTTP caches remain outside the repository.

Sync changes only paths owned by a job, a wrapper marker, or recorded managed state.

The main caches use these default paths. `XDG_CACHE_HOME` replaces `~/.cache` for managed releases and harness packages when the variable is set.

| Path | Contents |
| --- | --- |
| `~/.cache/agents/model-catalog/` | Cached models.dev, provider, and gateway responses |
| `<cache-home>/github-tools/cliproxyapi/` | Verified CLIProxyAPI releases |
| `<cache-home>/npm-tools/` | Versioned harness npm packages |
