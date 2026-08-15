# Sync

Sync reconciles committed sources into tool homes. It is idempotent: a repeated run with unchanged inputs does not replace unchanged files.

## Entrypoints

Run a manual sync from the repository root:

```bash
bun ./sync/src/cli.ts
```

Generated harness wrappers use:

```text
bun ~/.config/agents/sync/src/cli.ts launch <harness> -- <arguments>
```

`launch` performs a best-effort sync, prepares the cached harness package, and executes it. A sync failure does not block an already cached harness.

## Reconciliation order

A sync run performs these stages:

1. Build the sync and cleanup plans.
2. Remove stale managed harness entries.
3. Copy shared and harness-specific configuration.
4. Render secret templates and CLIProxyAPI configuration.
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
