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
| `runtimeSubdir` | Subdirectory appended to the source and generated roots |
| `compatManagedEntries` | Obsolete generated entries that sync can remove |
| `hooks` | Package-bootstrap and extension-dependency jobs |

Without `runtimeSubdir`, the source root is `harnesses/<id>/` and the generated root comes from `homeSegments`. With `runtimeSubdir`, sync appends that value to both roots.

## Published configuration

Sync publishes the repository's `HARNESS.md` as the harness instruction file (`AGENTS.md` unless the adapter sets `instructionFile`) and `skills/current/` as `skills/` to every enabled harness. Tool sources under `tools/` are repository-only and never published.

Adapters can declare these hooks:

- `PackageBootstrap` prepares packages from the adapter's source manifest and updates runtime settings.
- `ExtensionDeps` installs dependencies for generated TypeScript extensions and plugins when the hook inputs change. Runtime imports belong in the generated root's committed `package.json`; the hook preserves its generated `node_modules` and lockfile while the source fingerprint is unchanged.

## CLIProxyAPI integration

A harness uses CLIProxyAPI when its committed source defines a `cliproxy` provider. Sync does not inject a provider or manage client credentials. OpenCode, OMP, and Pi use the `keyless` placeholder in their CLIProxyAPI entries. Codex does not configure a client key. Sync probes the gateway without authorization.

Sync replaces `${CLIPROXY_CLIENT_BASE_URL}` in the committed harness source with `client.baseUrl` from `tools/cliproxyapi/deployment.json`. Harness providers use a static placeholder key because their SDKs require a non-empty value. The gateway ignores that key.

Harnesses use their native model discovery or configured model definitions against the gateway endpoint.
## Launch wrappers

Sync writes wrappers under `~/.local/bin/` and expects that directory on `PATH`.

Each wrapper calls the installed sync runtime at `~/.local/share/agents/sync-current/src/cli.ts` with `launch`, prepares the cached npm package, forwards all arguments, and returns the harness exit status.

When the installed sync runtime is missing, the wrapper prints a hint to run sync from the agents repository and exits with status `127`.

The wrapper command is `launcher.bin`. The wrapper passes the adapter `id` to the installed runtime, so the command and source directory name can differ.

Wrapper state lives at `~/.local/share/agents/sync-managed/wrappers.json`. Sync removes stale wrappers only when they contain its ownership marker and remain in an allowed wrapper directory. Sync preserves unmanaged conflicts and reports them.

## Package cache

Each harness has a versioned npm cache under `<cache-home>/npm-tools/`. `<cache-home>` is `XDG_CACHE_HOME` or `~/.cache`.

The cache keeps the current and previous known-good package versions. Newly installed packages pass the adapter smoke command before promotion. Cached packages are checked for package identity and an executable before promotion.

## Shared harness environment

`sync` resolves shared environment variables from `.env` in the repository root (`~/.config/agents/.env`).

- If `.env` is absent, `sync` continues with an empty default environment map.
- Variables are decoded at the `SyncEnv` boundary using Effect `ConfigProvider.fromDotEnvContents` without variable expansion, preserving quoted and unquoted strings as well as literal variable syntax while omitting empty values.
- Decoded variables are forwarded to child processes for all supported harnesses (`codex`, `deepseek`, `grok`, `opencode`, `pi`, and `omp`).
- Precedence:
  1. Explicit adapter overrides (`launcher.env`).
  2. Parent-process environment variables inherited from the invoking environment.
  3. Default values defined in `.env`.
- Generated launch wrappers under `~/.local/bin/` do not embed `.env` values; they dynamically invoke the sync runtime on each launch.
