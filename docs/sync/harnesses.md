# Harness adapter reference

`HARNESS_ADAPTERS` in `sync/src/sync/core/harness_adapters.py` defines the adapters that sync understands. A matching directory under `harnesses/` enables an adapter when the current platform appears in its `platforms` field.

Harness-specific values, such as package names, distribution tags, default launch arguments, environment variables, manager setting keys, install paths, and preserved JSON paths, live in the adapter definitions and in `harnesses/<id>/`. This page describes mechanisms only; read the harness source for the values it owns.

Sync supports macOS and Linux.

## Adapter fields

| Field | Meaning |
| --- | --- |
| `id` | Adapter ID, source directory name, package-cache name, and launch argument |
| `home_segments` | Path components from the user home to the generated harness home |
| `platforms` | Host platforms on which sync enables the adapter; every adapter declares both `darwin` and `linux`, and static release `targets` cover `arm64` and `x64` on each |
| `launcher` | npm or static release launcher specification |
| `launcher.default_args` | Arguments that sync places in the wrapper before caller arguments |
| `launcher.env` | Environment variables baked into the wrapper as `export` lines and applied to every launch; they override both the parent environment and `.env` |
| `instruction_file` | Harness instruction filename when it differs from `AGENTS.md` |
| `runtime_subdir` | Subdirectory appended to the source and generated roots |
| `compat_managed_entries` | Obsolete generated entries that sync can remove |
| `preserve_json_keys` | Source JSON files sync copies over the generated file, re-injecting only the listed dot-paths from the previous file |
| `cliproxy_templates` | Source-relative paths whose `${CLIPROXY_CLIENT_BASE_URL}` or `${CLIPROXY_CLIENT_ORIGIN}` placeholders sync replaces; only declared paths that actually contain a placeholder are replaced |
| `cliproxy_preserve_top_levels` | Per-template TOML table names re-injected from the previous generated file during endpoint publication |
| `python_env_segments` | Home-relative segments of the uv-managed Python environment sync bootstraps before reconciliation |
| `hooks` | Package-bootstrap and extension-dependency jobs |

Without `runtime_subdir`, the source root is `harnesses/<id>/` and the generated root comes from `home_segments`. With `runtime_subdir`, sync appends that value to both roots.

## Published configuration

Sync publishes the repository's `HARNESS.md` as the harness instruction file (`AGENTS.md` unless the adapter sets `instruction_file`) and `skills/current/` as `skills/` to every enabled harness. Sync never publishes `tools/` into a harness home; it copies or renders selected tool files into each tool's own home, as the [Sync reference](sync.md#tool-launchers) describes.

The Pi adapter also renders native MCP configuration from `tools/mcporter/mcporter.jsonc` through `sync/src/sync/core/pi_mcp.py`. A server's `piSkill` names the shared skill replaced by that native entry. Sync appends exact skill-path exclusions to the tracked Pi settings and records the generated files as managed entries. Each reconciliation replaces the server map and derives exclusions from the current registry, so removed servers and their exclusions disappear. Other adapters retain the shared skills and mcporter configuration unchanged. See the [Pi harness source](../../harnesses/pi/README.md#native-mcp) for runtime behavior and credential handling.

## Launchers

Sync supports two launcher kinds, discriminated by the adapter's `launcher` value.

- `NpmLauncherSpec` installs a versioned npm package. `package`, `bin`, `dist_tag`, and `smoke_check` describe it.
- `StaticReleaseLauncherSpec` installs a versioned archive from a static JSON manifest that its `release` field (`StaticReleaseSpec`) describes. `manifest_url` points at the manifest, `targets` maps `<platform>-<arch>` keys to the manifest's platform keys, `install_segments` is the home-relative install root, and `executable_segments` is the path to the binary inside the extracted version directory.

A static release manifest has the shape `{"version": "1.2.3", "platforms": {"<platform-key>": {"url": "...", "sha256": "..."}}}`. Sync resolves the manifest, verifies the archive SHA-256, extracts it into `<install root>/_versions/<version>/`, writes the distribution marker, and rotates the `current` and `previous` symlinks. An already installed version is reused without re-downloading, and a failed manifest lookup or installation falls back to the current cached install.

When `man_segments` and `man_dest_segments` are set, sync also publishes versioned man page symlinks into the destination directory and removes owned stale links whose target points into the install root. It never removes unrelated entries in the shared man directory.

Adapters can declare these hooks:

- `PackageBootstrapHook` prepares packages from the adapter's source manifest and updates runtime settings.
- `ExtensionDepsHook` installs dependencies for generated extensions and plugins when the hook inputs change. Runtime imports belong in the generated root's committed `package.json`; the hook preserves its generated `node_modules` and lockfile while the source fingerprint is unchanged.

## CLIProxyAPI integration

A harness uses CLIProxyAPI when its committed source defines a `cliproxy` provider or points its API base URL at an endpoint placeholder. Sync does not inject a provider or manage client credentials, and it probes the gateway without authorization.

Sync replaces `${CLIPROXY_CLIENT_BASE_URL}` in the committed harness source with `client.baseUrl` from `tools/cliproxyapi/deployment.json`, and `${CLIPROXY_CLIENT_ORIGIN}` with the same URL without its `/v1` path, for clients that append the version path themselves (Claude Code's `ANTHROPIC_BASE_URL`). A provider that requires a non-empty client key uses a static placeholder, which the gateway ignores. The replacement targets are the adapter's `cliproxy_templates`; sync checks each declared path for either placeholder, so a stale declaration without one is inert. When publishing those targets, `cliproxy_preserve_top_levels` re-injects the named TOML tables from the previous generated file. It is TOML-table scoped and distinct from `preserve_json_keys`, which carries JSON dot-paths.

Harnesses use their native model discovery or configured model definitions against the gateway endpoint.
## Launch wrappers

Sync writes wrappers under `~/.local/bin/` and expects that directory on `PATH`.

Each wrapper calls the installed sync runtime at `~/.local/share/agents/sync-current/.venv/bin/python -m sync.cli` with `launch`, prepares the harness launcher, and replaces itself with the harness, forwarding all arguments. The harness exit status is the wrapper's exit status.

When the installed sync runtime is missing, the wrapper prints a hint to run sync from the agents repository and exits with status `127`.

The wrapper command is `launcher.bin`. The wrapper passes the adapter `id` to the installed runtime, so the command and source directory name can differ.

Wrapper state lives at `~/.local/share/agents/sync-managed/wrappers.json`. Sync removes stale wrappers only when they contain its ownership marker and remain in an allowed wrapper directory. Sync preserves unmanaged conflicts and reports them.

## Preserved JSON keys

`preserve_json_keys` maps each source JSON filename to the dot-paths allowed to survive from the previous generated file. Sync copies the source file verbatim over the destination, then re-injects each declared path's previous value only where the source leaves it undefined: the source wins collisions, paths absent from the destination are skipped, and undeclared destination keys are removed. An empty path list is a pure copy, and a missing source file is a sync error.

## Package cache

Each npm harness has a versioned cache under `<cache-home>/npm-tools/`. `<cache-home>` is `XDG_CACHE_HOME` or `~/.cache`.

The cache keeps the current and previous known-good package versions, and any older version a running process still executes (see [Launch behavior](sync.md#launch-behavior)). Newly installed packages pass the adapter smoke command before promotion. Cached packages are checked for package identity and an executable before promotion. Changing an adapter's npm package selects a separate package-key cache; it does not reuse the previous package's `current` install. The wrapper name and generated home can remain unchanged during that migration.

Static release harnesses install one directory per resolved manifest version under the adapter's `install_segments` root instead of the npm cache. Those installs also keep the current and previous versions.

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
