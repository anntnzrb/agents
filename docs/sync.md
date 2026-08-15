# Sync

Sync reconciles committed sources into tool homes. It is idempotent: a repeated run with unchanged inputs does not replace unchanged files.

## Entrypoints

Run a manual sync from the repository root:

```bash
bun ./sync/src/cli.ts
```

Force model-catalog revalidation even when the cache is fresh:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

Generated harness wrappers use:

```text
bun ~/.local/share/agents/sync/src/cli.ts launch <harness> -- <arguments>
```

`launch` performs a best-effort sync when `~/.config/agents` is available, prepares the cached harness package, and executes it. A sync failure or unavailable SSOT does not block an already cached harness.

## Reconciliation order

A sync run performs these stages:

1. Build the sync and cleanup plans.
2. Remove stale managed harness entries.
3. Install the sync runtime and copy shared and harness-specific configuration.
4. Refresh cached model catalogs and render secret templates and CLIProxyAPI configuration.
5. Prepare pinned managed tools.
6. Reconcile launch wrappers.
7. Record managed state.
8. Run package and extension hooks.

A process lock prevents concurrent sync runs from writing the same targets.

## Secret templates

`SecretTemplate` jobs read placeholders from a committed template and values from `secrets.local.json`. The renderer validates the JSON once, JSON-quotes each value for YAML, and writes the target atomically with mode `0600`.

If `secrets.local.json` does not exist, sync warns and preserves any existing generated target. If the file exists but lacks a required value, sync fails.

## CLIProxyAPI configuration

The `CliProxyConfig` job parses `assets/cliproxyapi.yaml.tmpl` as YAML and injects typed values from `secrets.local.json`. A template entry with `x-credential-pool` references one provider pool.

For native API-key sections, sync duplicates the shared provider profile once per account. For `openai-compatibility`, sync generates one `api-key-entries` item per account. The `x-credential-pool` marker never appears in the generated config.

The renderer uses Bun's YAML parser and serializer, validates all pool references, and writes the target atomically with mode `0600`. Missing local secrets preserve an existing generated target; malformed credentials fail sync without replacing it.

### Model catalogs

`x-model-sources` in `assets/cliproxyapi.yaml.tmpl` declares provider endpoints, credential pools, public prefixes, and matching [models.dev](https://models.dev/) provider IDs. It does not list model IDs.

Sync fetches each provider's authenticated `/models` catalog and intersects it with models.dev metadata. The live provider catalog decides availability. Models.dev supplies protocol, capabilities, modalities, context and output limits, and published costs. Sync groups models by protocol and generates CLIProxyAPI `codex-api-key`, `claude-api-key`, and `openai-compatibility` profiles.

Raw HTTP catalog responses are cached under:

```text
~/.cache/agents/model-catalog/
```

Models.dev metadata is fresh for one hour. Provider catalogs are fresh for six hours. Sync sends cached ETags during revalidation, uses a stale cache after transient failures, and keeps launch-time refresh warnings quiet. `sync --refresh-models` bypasses freshness windows and fails instead of silently accepting stale network data.

The normalized, harness-independent runtime catalog is `~/.local/share/agents/model-catalog/catalog.json`. Sync also writes the first configured client key to `~/.local/share/agents/cliproxyapi/client-api-key` with mode `0600`. Generated model IDs and metadata are deterministic, and unchanged syncs do not replace either file.

After publishing the runtime catalog, sync removes the deprecated `~/.cache/agents/model-catalog/catalog.json`. The remaining files in that cache directory are HTTP response caches.

## Installed runtime

Sync copies its dependency-free runtime source and `tsconfig.json` to:

```text
~/.local/share/agents/sync/
```

Harness wrappers execute this installed copy. Only sync reads the SSOT under `~/.config/agents`; harnesses and their runtime adapters read generated homes or installed state under `~/.local/share/agents`.

## Managed tools

`assets/cliproxyapi.release.json` pins CLIProxyAPI by version, platform asset, and SHA-256 checksum. Sync downloads the official GitHub release only when the pinned executable is absent.

The cache path is:

```text
~/.cache/github-tools/cliproxyapi/versions/<version>/<platform>-<architecture>/
```

Sync extracts only the executable named by the manifest. It then generates a stable command in `~/.local/bin`.

## Managed state

Sync records ownership under `~/.local/share/agents/sync-managed`. Cleanup removes only entries that previous sync state owns. Unmanaged wrapper conflicts are preserved and reported.

## Missing sources

Most missing source directories are non-fatal. This permits partial harness configurations. Invalid committed configuration and failed first-time managed-tool installation are fatal.
