# Harness adapter reference

`HARNESS_ADAPTERS` in `sync/src/sync/core/harness_adapters.py` defines the adapters that sync understands. A matching directory under `harnesses/` enables an adapter when the current platform appears in its `platforms` field.

Sync supports macOS and Linux. The current CLIProxyAPI release manifest supports macOS ARM64 and Linux x86_64.

## Adapter fields

| Field | Meaning |
| --- | --- |
| `id` | Adapter ID, source directory name, package-cache name, and launch argument |
| `homeSegments` | Path components from the user home to the generated harness home |
| `platforms` | Host platforms on which sync enables the adapter |
| `launcher` | npm or static release launcher specification |
| `launcher.defaultArgs` | Arguments that sync places in the wrapper before caller arguments |
| `launcher.env` | Environment variables baked into the wrapper as `export` lines and applied to every launch; they override both the parent environment and `.env` |
| `instructionFile` | Harness instruction filename when it differs from `AGENTS.md` |
| `runtimeSubdir` | Subdirectory appended to the source and generated roots |
| `compatManagedEntries` | Obsolete generated entries that sync can remove |
| `mergeJsonFiles` | Source JSON files sync deep-merges over the generated file instead of copying |
| `hooks` | Package-bootstrap and extension-dependency jobs |

Without `runtimeSubdir`, the source root is `harnesses/<id>/` and the generated root comes from `homeSegments`. With `runtimeSubdir`, sync appends that value to both roots.

## Published configuration

Sync publishes the repository's `HARNESS.md` as the harness instruction file (`AGENTS.md` unless the adapter sets `instructionFile`) and `skills/current/` as `skills/` to every enabled harness. Tool sources under `tools/` are repository-only and never published.

## Launchers

Sync supports two launcher kinds, discriminated by the adapter's `launcher` value.

- `NpmLauncherSpec` installs a versioned npm package. `package`, `bin`, `distTag`, and `smokeCheck` describe it.
- `StaticReleaseLauncherSpec` installs a versioned archive from a static JSON manifest. `manifestUrl` points at the manifest, `targets` maps `<platform>-<arch>` keys to the manifest's platform keys, `installSegments` is the home-relative install root, and `executableSegments` is the path to the binary inside the extracted version directory.

A static release manifest has the shape `{"version": "1.2.3", "platforms": {"<platform-key>": {"url": "...", "sha256": "..."}}}`. Sync resolves the manifest, verifies the archive SHA-256, extracts it into `<install root>/_versions/<version>/`, writes the distribution marker, and rotates the `current` and `previous` symlinks. An already installed version is reused without re-downloading, and a failed manifest lookup or installation falls back to the current cached install.

When `manSegments` and `manDestSegments` are set, sync also publishes versioned man page symlinks into the destination directory and removes owned stale links whose target points into the install root. It never removes unrelated entries in the shared man directory.

Devin uses a static release launcher. Sync installs the current release into `~/.local/share/devin/cli/_versions/` and publishes the `devin` wrapper. The merged user config sets `auto_update: false` so Devin's background updater never replaces the sync-managed install. The adapter sets `DEVIN_PERMISSION_MODE=bypass` via `launcher.env`, so every wrapper launch auto-approves all tool calls; `--permission-mode` on the command line still overrides it per invocation.

Adapters can declare these hooks:

- `PackageBootstrap` prepares packages from the adapter's source manifest and updates runtime settings.
- `ExtensionDeps` installs dependencies for generated extensions and plugins when the hook inputs change. Runtime imports belong in the generated root's committed `package.json`; the hook preserves its generated `node_modules` and lockfile while the source fingerprint is unchanged.

## CLIProxyAPI integration

A harness uses CLIProxyAPI when its committed source defines a `cliproxy` provider. Sync does not inject a provider or manage client credentials, and it probes the gateway without authorization.

Sync replaces `${CLIPROXY_CLIENT_BASE_URL}` in the committed harness source with `client.baseUrl` from `tools/cliproxyapi/deployment.json`. A provider that requires a non-empty client key uses a static placeholder, which the gateway ignores.

Harnesses use their native model discovery or configured model definitions against the gateway endpoint.
## Launch wrappers

Sync writes wrappers under `~/.local/bin/` and expects that directory on `PATH`.

Each wrapper calls the installed sync runtime at `~/.local/share/agents/sync-current/.venv/bin/python -m sync.cli` with `launch`, prepares the harness launcher, forwards all arguments, and returns the harness exit status.

When the installed sync runtime is missing, the wrapper prints a hint to run sync from the agents repository and exits with status `127`.

The wrapper command is `launcher.bin`. The wrapper passes the adapter `id` to the installed runtime, so the command and source directory name can differ.

Wrapper state lives at `~/.local/share/agents/sync-managed/wrappers.json`. Sync removes stale wrappers only when they contain its ownership marker and remain in an allowed wrapper directory. Sync preserves unmanaged conflicts and reports them.

## Merged JSON configuration

`mergeJsonFiles` lists source JSON files that must not overwrite machine-owned keys. Sync deep-merges the source object over the existing destination: nested objects merge by key, managed scalar and array values win, and destination-only keys survive. This keeps live fields such as Devin's org identifier while the SSOT owns preferences such as `auto_update`.

## Package cache

Each npm harness has a versioned cache under `<cache-home>/npm-tools/`. `<cache-home>` is `XDG_CACHE_HOME` or `~/.cache`.

The cache keeps the current and previous known-good package versions. Newly installed packages pass the adapter smoke command before promotion. Cached packages are checked for package identity and an executable before promotion.

Static release harnesses install one directory per resolved manifest version under the adapter `installSegments` root instead of the npm cache. Those installs also keep the current and previous versions.

## Shared harness environment

`sync` resolves shared environment variables from `.env` in the repository root (`~/.config/agents/.env`).

- If `.env` is absent, `sync` continues with an empty default environment map.
- Variables are decoded at the `SyncEnv` boundary with variable expansion disabled, preserving quoted and unquoted strings as well as literal variable syntax while omitting empty values.
- Decoded variables are forwarded to child processes of every enabled harness.
- Precedence:
  1. Explicit adapter overrides (`launcher.env`).
  2. Parent-process environment variables inherited from the invoking environment.
  3. Default values defined in `.env`.
- Generated launch wrappers under `~/.local/bin/` do not embed `.env` values; they dynamically invoke the sync runtime on each launch.
