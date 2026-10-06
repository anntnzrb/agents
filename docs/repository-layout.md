# Repository layout

The repository separates committed sources, local inputs, generated targets, and runtime state.

## Committed sources

| Path | Contents |
| --- | --- |
| `AGENTS.md` | Repository policy for contributors and agents |
| `HARNESS.md` | Global harness-independent agent instructions; sync publishes it to every harness as its instruction file |
| `agents.toml` | Settings shared by several harnesses and tools; see [Shared settings](sync/sync.md#shared-settings-and-gateway-endpoints) |
| `skills/current/` | Shared skills published to enabled harnesses |
| `skills/legacy/` | Archived skills excluded from sync |
| `harnesses/<harness>/` | Harness-owned configuration, implementation, adjacent tests, and local documentation |
| `tools/` | Configuration sources for sync-managed CLI tools |
| `sync/` | The Python (uv) sync application |
| `docs/` | Repository workflow documentation indexed by `docs/index.md`; sync application documentation under `docs/sync/` |
| `.github/` | CI workflows, their orchestration scripts, and adjacent tests; see [Verify a change in CI](ci.md) |
| `.githooks/` | Local Git hooks; see [Git hooks](../.githooks/README.md) |
| `.env.example` | Template and guidance for shared harness environment variables |

### Harness sources

Each harness source starts under `harnesses/<id>/`. When an adapter defines `runtime_subdir`, sync appends that subdirectory to the source root.

`sync/src/sync/core/harness_adapters.py` defines the supported harness IDs, package launchers, generated homes, platforms, runtime subdirectories, and hooks. A matching directory under `harnesses/` enables that adapter on a supported platform.

### Sync application

| Path | Purpose |
| --- | --- |
| `sync/src/sync/cli.py` (`sync` console script) | Public command entrypoint |
| `sync/src/sync/core/` | Plans, jobs, adapters, wrappers, and managed tools |
| `sync/src/sync/extensions/` | Extension dependency hooks |
| `sync/src/sync/packages/` | Harness package bootstrap logic |
| `sync/src/sync/runtime/` | Filesystem, JSONC, process, lock, and error boundaries |
| `sync/tests/` | Unit and process-level integration tests for sync behavior |

## Local inputs

`.env` contains host-local default environment variables forwarded to launched harnesses. The repository ignores it. Create it from `.env.example` and restrict permissions with `chmod 600`.

## Generated targets

For each harness, `home_segments` defines the generated harness home. When the adapter defines `runtime_subdir`, sync appends that subdirectory to the generated root.

Other jobs use fixed generated targets:

| Path | Owner |
| --- | --- |
| `~/.local/share/agents/sync-releases/<releaseId>/` | Installed sync runtime releases |
| `~/.local/share/agents/sync-current` | Symlink to the current installed sync runtime |
| `~/.local/share/agents/sync-managed/` | Managed ownership and hook state |
| `~/.local/share/agents/agents.toml` | Installed copy of `agents.toml` |
| `~/.local/bin/` | Harness and tool wrappers |
| `~/.mcporter/mcporter.json`, `~/.summarize/config.json` | Tool configuration copied from `tools/`; see [Tool launchers](sync/sync.md#tool-launchers) |

Sync replaces managed content in these targets. Make durable changes in the matching committed source.

## Runtime state

Credentials, OAuth files, sessions, logs, databases, and HTTP caches remain outside the repository.

Sync changes only paths owned by a job, a wrapper marker, or recorded managed state.

The main caches use these default paths. `XDG_CACHE_HOME` replaces `~/.cache` for harness packages when the variable is set:

| Path | Contents |
| --- | --- |
| `<cache-home>/npm-tools/` | Versioned harness npm packages |
