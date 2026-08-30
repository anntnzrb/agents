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
| `tools/` | Managed-tool sources |
| `sync/` | The Cargo workspace for the native Agentium synchronization engine and launcher |
| `docs/` | Repository workflow documentation indexed by `docs/index.md`; sync application documentation under `docs/sync/` |
| `secrets.local.example.json` | Schema and placeholder values for local CLIProxyAPI secrets |
| `.env.example` | Template and guidance for shared harness environment variables |

### Harness sources

Each harness source starts under `harnesses/<id>/`. When an adapter defines `runtimeSubdir`, sync appends that subdirectory to the source root.

`sync/crates/app-core/src/harness_adapters.rs` defines the supported harness IDs, package launchers, generated homes, platforms, runtime subdirectories, and hooks. A matching directory under `harnesses/` enables that adapter on a supported platform.

### Sync application

| Path | Purpose |
| --- | --- |
| `sync/Cargo.toml` | Cargo workspace root manifest |
| `sync/crates/app/` | Native CLI binary crate (`agentium`) |
| `sync/crates/app-core/` | Core library crate containing plans, jobs, adapters, wrappers, managed tools, launchers, and model catalog engine |

## Local inputs

`secrets.local.json` contains host-local CLIProxyAPI credentials. The repository ignores it. Create it from `secrets.local.example.json` and keep it outside Git.

`.env` contains host-local default environment variables forwarded to launched harnesses. The repository ignores it. Create it from `.env.example` and restrict permissions with `chmod 600`.

## Generated targets

For each harness, `homeSegments` defines the generated harness home. When the adapter defines `runtimeSubdir`, sync appends that subdirectory to the generated root.

Other jobs use fixed generated targets:

| Path | Owner |
| --- | --- |
| `~/.local/share/agentium/model-catalog/catalog.json` | Shared model-catalog job |
| `~/.local/share/agentium/sync-managed/` | Managed ownership and hook state |
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
