# Harness adapter reference

`HARNESS_ADAPTERS` in `sync/src/core/harness-adapters.ts` is the source of truth for supported harnesses. A matching directory under `harnesses/` enables an adapter when the current platform appears in its `platforms` field.

Sync supports macOS and Linux only. The current CLIProxyAPI release manifest supports macOS ARM64 and Linux x86_64.

## Adapter metadata

| Field | Meaning |
| --- | --- |
| `id` | Adapter ID, source directory name, package-cache name, and launch argument |
| `homeSegments` | Path components from the user home to the generated harness home |
| `platforms` | Host platforms on which sync enables the adapter |
| `launcher` | npm package, executable name, dist-tag, and smoke command |
| `launcher.defaultArgs` | Optional arguments sync renders into the wrapper before caller arguments |
| `instructionFile` | Harness instruction filename when it differs from `AGENTS.md` |
| `assetRenames` | Destination names for shared assets |
| `runtimeSubdir` | Optional subdirectory appended to both the source and generated roots |
| `compatManagedEntries` | Obsolete generated entries that sync can remove |
| `hooks` | Optional package-bootstrap and extension-dependency jobs |

Without `runtimeSubdir`, the source root is `harnesses/<id>/` and the generated root comes from `homeSegments`. With `runtimeSubdir`, sync appends that value to both roots.

## Shared configuration

Sync publishes `assets/AGENTS.md` and `skills/current/` to every enabled harness. Sync also publishes shared asset directories under `assets/`; the repository-only `assets/cliproxyapi/` directory is excluded. The `instructionFile` and `assetRenames` fields control destination names.

Adapters can declare these hooks:

- `PackageBootstrap` prepares packages declared by the adapter's source manifest and updates runtime settings.
- `ExtensionDeps` installs dependencies for generated extensions when the hook inputs change.

## CLIProxyAPI integration

A harness uses CLIProxyAPI only when its committed source defines a `cliproxy` provider. Sync has no adapter-wide injection step and does not manage client credentials; the gateway accepts requests without client keys, and the tailnet is the access boundary.

Sync replaces `${CLIPROXY_CLIENT_BASE_URL}` in the committed harness source with `client.baseUrl` from `assets/cliproxyapi/deployment.json`. Harness providers use a static placeholder API key because their SDKs require a non-empty value; the gateway ignores it. A harness can use native model discovery or read `~/.local/share/agents/model-catalog/catalog.json` through the installed runtime client. The harness source owns its model-selector syntax and discovery adapter.

API-key model IDs use the prefix declared by `x-model-sources`. The committed prefixes are `go`, `deepseek`, `zen`, and `cline-pass`. OAuth model IDs use the prefix stored in their CLIProxyAPI auth files, such as `chatgpt`, `antigravity`, or `grok`.

## Launch wrappers

Sync writes wrappers under `~/.local/bin/` and assumes that directory is on `PATH`.

Each wrapper calls the installed sync runtime with the `launch` command. The launch path attempts reconciliation, prepares the cached npm package, forwards all arguments, and returns the harness exit status.

When the installed sync runtime is missing, the wrapper prints a hint to run sync from the agents repository and exits with status `127` instead of failing with a raw interpreter error.

The wrapper command is `launcher.bin`. The wrapper passes the adapter `id` to the installed runtime, so the command and the source directory name do not need to match.

A `launcher.defaultArgs` list is rendered into the wrapper before `"$@"`, so those arguments reach the harness binary before anything the caller supplies.

Wrapper state lives at `~/.local/share/agents/sync-managed/wrappers.json`. Sync removes stale wrappers only when they contain its ownership marker and remain in an allowed wrapper directory. Unmanaged conflicts are preserved and reported.

## Package cache

Each harness has a versioned npm cache under `<cache-home>/npm-tools/`. `<cache-home>` is `XDG_CACHE_HOME` or `~/.cache`.

The cache keeps the current and previous known-good package versions. The launcher checks the package identity, executable, and adapter smoke command before promoting a version.
