# Harness adapter reference

`HARNESS_ADAPTERS` in `sync/src/core/harness-adapters.ts` defines the adapters that sync understands. A matching directory under `harnesses/` enables an adapter when the current platform appears in its `platforms` field.

Sync supports macOS and Linux. The current CLIProxyAPI release manifest supports macOS ARM64 and Linux x86_64.

## Adapter fields

| Field | Meaning |
| --- | --- |
| `id` | Adapter ID, source directory name, package-cache name, and launch argument |
| `homeSegments` | Path components from the user home to the generated harness home |
| `platforms` | Host platforms on which sync enables the adapter |
| `launcher` | npm package, executable name, dist-tag, and smoke command |
| `launcher.defaultArgs` | Arguments that sync places in the wrapper before caller arguments |
| `instructionFile` | Harness instruction filename when it differs from `AGENTS.md` |
| `assetRenames` | Destination names for shared assets |
| `runtimeSubdir` | Subdirectory appended to the source and generated roots |
| `compatManagedEntries` | Obsolete generated entries that sync can remove |
| `hooks` | Package-bootstrap and extension-dependency jobs |

Without `runtimeSubdir`, the source root is `harnesses/<id>/` and the generated root comes from `homeSegments`. With `runtimeSubdir`, sync appends that value to both roots.

## Published configuration

Sync publishes `assets/AGENTS.md`, `skills/current/`, and shared asset directories under `assets/` to every enabled harness. It excludes the repository-only `assets/cliproxyapi/` directory. The `instructionFile` and `assetRenames` fields control destination names.

Adapters can declare these hooks:

- `PackageBootstrap` prepares packages from the adapter's source manifest and updates runtime settings.
- `ExtensionDeps` installs dependencies for generated extensions when the hook inputs change.

## CLIProxyAPI integration

A harness uses CLIProxyAPI when its committed source defines a `cliproxy` provider. Sync does not inject a provider or manage client credentials. OpenCode, OMP, and Pi use the `keyless` placeholder in their CLIProxyAPI entries. Codex does not configure a client key. Sync probes the gateway without authorization.

Sync replaces `${CLIPROXY_CLIENT_BASE_URL}` in the committed harness source with `client.baseUrl` from `assets/cliproxyapi/deployment.json`. Harness providers use a static placeholder key because their SDKs require a non-empty value. The gateway ignores that key.

Harnesses can use native model discovery or read `~/.local/share/agents/model-catalog/catalog.json` through their runtime integration. Each harness owns its model-selector syntax and discovery adapter.

API-key model IDs use the prefix declared by `x-model-sources`. OAuth model IDs use the prefix stored in the CLIProxyAPI auth files.

## Launch wrappers

Sync writes wrappers under `~/.local/bin/` and expects that directory on `PATH`.

Each wrapper calls the installed sync runtime with `launch`, prepares the cached npm package, forwards all arguments, and returns the harness exit status.

When the installed sync runtime is missing, the wrapper prints a hint to run sync from the agents repository and exits with status `127`.

The wrapper command is `launcher.bin`. The wrapper passes the adapter `id` to the installed runtime, so the command and source directory name can differ.

Wrapper state lives at `~/.local/share/agents/sync-managed/wrappers.json`. Sync removes stale wrappers only when they contain its ownership marker and remain in an allowed wrapper directory. Sync preserves unmanaged conflicts and reports them.

## Package cache

Each harness has a versioned npm cache under `<cache-home>/npm-tools/`. `<cache-home>` is `XDG_CACHE_HOME` or `~/.cache`.

The cache keeps the current and previous known-good package versions. Newly installed packages pass the adapter smoke command before promotion. Cached packages are checked for package identity and an executable before promotion.
