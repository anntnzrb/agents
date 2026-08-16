# Sync reference

Sync reconciles the repository source at `~/.config/agents` with harness homes and installed runtime state. The public entrypoint is `sync/src/cli.ts` and requires an explicit Bun runner.

## Command syntax

| Invocation | Behavior |
| --- | --- |
| `bun ./sync/src/cli.ts` | Runs a normal reconciliation |
| `bun ./sync/src/cli.ts sync` | Runs the same normal reconciliation |
| `bun ./sync/src/cli.ts sync --refresh-models` | Bypasses model-catalog freshness windows and disallows stale network data |
| `bun ~/.local/share/agents/sync/src/cli.ts launch <harness> -- <arguments>` | Syncs when the source is available, prepares the harness package, and launches it |

Unknown commands and invalid arguments exit with status `2`. A manual sync exits with status `1` after a fatal reconciliation error.

## Reconciliation stages

A manual sync uses this order:

1. Build the sync plan and the managed cleanup plan.
2. Remove stale top-level harness entries owned by earlier sync state.
3. Install the sync runtime and reconcile source files, shared assets, skills, and generated configuration.
4. On the gateway host only, prepare managed tools from committed release manifests.
5. Reconcile harness and managed-tool wrappers, removing stale owned managed-tool wrappers on client hosts.
6. Record managed harness entries.
7. Run package bootstrap and extension dependency hooks.

The process lock is `~/.local/share/agents/sync-managed/sync.lock`. A second manual sync reports the lock and exits with status `0` without changing targets. A watchdog ends a manual sync after 15 minutes with status `124`.

## File reconciliation

Sync compares file content and modes before replacement. An unchanged run leaves matching files in place.

Directory jobs have one of two scopes:

- A tree job makes the destination tree match its source.
- A children job reconciles managed top-level entries inside an existing harness home.

Recorded ownership limits cleanup to safe top-level names. Sync preserves unmanaged wrapper conflicts and reports each conflict.

## Missing sources

Most missing source files and directories produce diagnostics but do not fail the run. Non-fatal missing-source errors permit partial harness sources.

Invalid committed configuration, malformed local secrets, hook failures, and a failed first managed-tool installation are fatal. A client host can operate without `secrets.local.json` when it has an installed runtime client key.

## CLIProxyAPI configuration job

The job reads `assets/cliproxyapi.yaml.tmpl` and `secrets.local.json`. The job writes these private files with mode `0600`:

- `~/.cli-proxy-api/config.yaml`
- `~/.local/share/agents/cliproxyapi/client-api-key`
- `~/.local/share/agents/model-catalog/catalog.json`

Sync validates `assets/cliproxyapi.deployment.json` before reconciliation. It injects `listen.host` and `listen.port` into the generated gateway configuration. It uses `client.baseUrl` for catalog discovery and health checks. The deployment file is the only source for these host and endpoint values.

The readiness job compares the local OS hostname with `server.hostname`:

- On the gateway host, the readiness state remains unset. The configuration job writes the server configuration, and endpoint publication checks the target afterward.
- On another host, the readiness job checks the configured `/models` target with the first candidate client key from `secrets.local.json`. If that key is unavailable, it uses the installed runtime client key.
- Without either key, sync preserves the existing client artifacts.
- An unavailable target leaves the existing CLIProxyAPI configuration, client key, model catalog, and harness endpoint files unchanged. It does not fail the initial client sync.
- A ready target lets the configuration job update the client key and model catalog without replacing the local server configuration.

Endpoint publication then replaces all configured `${CLIPROXY_CLIENT_BASE_URL}` harness targets as one transaction. Publication preserves the Codex-owned `[hooks.state]` and `[projects]` tail in `~/.codex/config.toml`. A write failure restores every endpoint's previous content and mode.

The renderer parses and serializes YAML with Bun. The renderer bcrypt-hashes the management key and reuses the existing hash when the plaintext key is unchanged. The renderer also expands each credential pool into the CLIProxyAPI profile type selected by model metadata.

The job writes files through a temporary file and an atomic rename. Invalid secrets or model data fail before the job replaces the generated configuration.

## Model-catalog caches

`assets/cliproxyapi.yaml.tmpl` declares provider endpoints, credential pools, public prefixes, and models.dev provider IDs under `x-model-sources`. Provider `/models` responses determine availability. [models.dev](https://models.dev/) supplies protocol hints and model metadata.

| Catalog | Freshness window | Cache file |
| --- | --- | --- |
| models.dev | 1 hour | `~/.cache/agents/model-catalog/models-dev.json` |
| Provider `/models` | 6 hours | `~/.cache/agents/model-catalog/source-<id>.json` |
| CLIProxyAPI `/v1/models` | 1 hour | `~/.cache/agents/model-catalog/gateway.json` |

Each cache entry records the request URL. Sync ignores a cache entry created for another URL, so an endpoint migration cannot reuse the old gateway response. Expired entries use ETag revalidation when the server supplied an ETag. A normal sync accepts a stale entry after a refresh error. A launch-time sync suppresses stale-cache warnings. A forced refresh rejects stale data.

After catalog publication, sync removes the obsolete `~/.cache/agents/model-catalog/catalog.json` file.

## Installed runtime

Sync copies `sync/src/` and `sync/tsconfig.json` to `~/.local/share/agents/sync/`. Generated wrappers execute this installed copy.

Only sync reads the repository source directly. Harness configuration and runtime adapters read generated homes or files under `~/.local/share/agents`.

## Managed CLIProxyAPI release

`assets/cliproxyapi.release.json` selects the GitHub repository, version, platform archive, and checksum. Sync downloads an archive only when the cached executable or its receipt does not match the manifest.

The cache path has this form, where `<cache-home>` is `XDG_CACHE_HOME` or `~/.cache`:

```text
<cache-home>/github-tools/cliproxyapi/versions/<version>/<platform>-<architecture>/
```

Sync verifies the SHA-256 checksum, extracts only the named executable, writes a receipt, and generates a stable wrapper. The current manifest contains macOS ARM64 and Linux x86_64 assets.

Sync prepares the managed CLIProxyAPI binary and its wrapper only on the gateway host (where the local hostname matches `server.hostname`). Client hosts never prepare managed tools; a previously owned `cli-proxy-api` wrapper recorded in wrapper state is reconciled away on the next sync.

## Launch behavior

Harness wrappers perform a best-effort sync before launch. A failed sync, an active sync lock, or an unavailable repository does not block a cached harness package.

The launcher resolves the adapter's npm dist-tag and installs the resolved version into a versioned cache. The launcher retains the current and previous known-good versions. If network resolution or a new package installation fails, the launcher uses the current valid cache. A first launch without a valid cache fails.
