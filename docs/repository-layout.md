# Repository layout

The repository separates committed sources from generated files and host-local runtime state.

## Committed sources

| Path | Contents |
| --- | --- |
| `AGENTS.md` | Repository policy for contributors and agents |
| `assets/` | Shared instructions, MCPorter configuration, CLIProxyAPI sources, and the skill gate |
| `skills/current/` | Shared skills published to enabled harnesses |
| `skills/legacy/` | Archived skills excluded from sync |
| `harnesses/<harness>/` | Source configuration for one supported harness |
| `sync/` | The Bun and TypeScript sync application |
| `docs/` | Repository documentation indexed by `docs/index.md` |
| `secrets.local.example.json` | Schema and placeholder values for local CLIProxyAPI secrets |
| `secrets.local.json` | Ignored host-local CLIProxyAPI secrets |

### Shared assets

| Path | Purpose |
| --- | --- |
| `assets/AGENTS.md` | Global harness-independent agent instructions |
| `assets/mcporter.jsonc` | MCPorter configuration source |
| `assets/cliproxyapi.yaml.tmpl` | CLIProxyAPI configuration template and model-source declarations |
| `assets/cliproxyapi.release.json` | Pinned release assets and SHA-256 checksums |
| `assets/skills-gate.md` | Policy and validation commands for shared skills |

### Harness sources

Codex, DeepSeek Harness, and OpenCode store their source files directly under `harnesses/<harness>/`. Pi and OMP use `harnesses/<harness>/agent/` as their runtime source.

`sync/src/core/harness-adapters.ts` defines the supported harness IDs, package launchers, generated homes, runtime subdirectories, and hooks. A matching directory under `harnesses/` enables that adapter.

### Sync application

| Path | Purpose |
| --- | --- |
| `sync/src/cli.ts` | Public command entrypoint |
| `sync/src/core/` | Plans, jobs, adapters, wrappers, managed tools, and model catalogs |
| `sync/src/extensions/` | Extension dependency hooks |
| `sync/src/packages/` | Harness package bootstrap logic |
| `sync/src/runtime/` | Filesystem, process, lock, and error boundaries |
| `sync/test/` | Unit and process-level integration tests |

## Generated targets

| Path | Owner |
| --- | --- |
| `~/.codex/` | Codex adapter |
| `~/.dsh/` | DeepSeek Harness adapter |
| `~/.config/opencode/` | OpenCode adapter |
| `~/.pi/agent/` | Pi adapter |
| `~/.omp/agent/` | OMP adapter |
| `~/.mcporter/mcporter.json` | MCPorter job |
| `~/.cli-proxy-api/config.yaml` | CLIProxyAPI configuration job |
| `~/.local/share/agents/sync/` | Installed sync runtime |
| `~/.local/share/agents/model-catalog/catalog.json` | Shared model-catalog job |
| `~/.local/share/agents/cliproxyapi/client-api-key` | CLIProxyAPI client-key job |
| `~/.local/share/agents/sync-managed/` | Managed ownership and hook state |
| `~/.local/bin/` | Unix harness and managed-tool wrappers |
| `%LOCALAPPDATA%/Programs/Agents/bin/` | Windows harness wrappers |

Sync replaces managed content in these targets. Durable changes belong in the matching committed source.

## Runtime state

Credentials, OAuth files, sessions, logs, databases, and HTTP caches remain outside the repository. Sync changes only paths owned by a job, a wrapper marker, or recorded managed state.

The main caches use these default paths. `XDG_CACHE_HOME` replaces `~/.cache` for managed releases and harness packages when the variable is set.

| Path | Contents |
| --- | --- |
| `~/.cache/agents/model-catalog/` | Cached models.dev, provider, and gateway responses |
| `<cache-home>/github-tools/cliproxyapi/` | Verified CLIProxyAPI releases |
| `<cache-home>/npm-tools/` | Versioned harness npm packages |
