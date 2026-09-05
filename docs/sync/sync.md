# Sync reference

Sync reconciles the repository at `~/.config/agents` with harness homes and installed runtime state on macOS and Linux. The public entrypoint is `sync/src/sync/cli.py` (console script `sync`) and requires an explicit `uv` runner.

A gateway host has an OS hostname that matches `server.hostname` in `tools/cliproxyapi/deployment.json`. Every other supported host is a client host.

## Command syntax

| Invocation | Behavior |
| --- | --- |
| `uv run --project sync sync` | Runs a normal reconciliation |
| `uv run --project sync sync sync` | Runs the same normal reconciliation |
| `~/.local/share/agents/sync-current/.venv/bin/python -m sync.cli launch <name> -- <arguments>` | Syncs when the source is available, prepares the harness or tool package, and launches it |

Unknown commands and invalid arguments exit with status `2`. A manual sync exits with status `1` after a fatal reconciliation error.

## Reconciliation stages

A manual sync runs these stages in order:

1. Build the sync plan and managed cleanup plan.
2. Remove stale top-level harness entries that earlier sync runs owned.
3. Install the sync runtime and reconcile source files, shared assets, skills, and generated configuration.
4. On the gateway host, prepare managed tools from the committed release manifest.
5. Reconcile harness, tool, and managed-tool wrappers. Remove stale owned CLIProxyAPI wrappers on client hosts.
6. Record managed harness entries.
7. Run package-bootstrap and extension-dependency hooks.

The process lock is `~/.local/share/agents/sync-managed/sync.lock`. A second manual sync reports the lock and exits with status `0` without changing targets. A watchdog ends a manual sync after 15 minutes with status `124`.

## File reconciliation

Sync compares file content and modes before replacement. An unchanged run leaves matching files in place.

Directory jobs use one of two scopes:

- A tree job makes the destination tree match its source.
- A children job reconciles managed top-level entries inside an existing harness home.

Recorded ownership limits cleanup to safe top-level names. Sync preserves unmanaged wrapper conflicts and reports each conflict.

## Missing sources and errors

Most missing source files and directories produce diagnostics but do not fail the run. Invalid committed configuration, malformed local secrets, hook failures, and a first managed-tool installation failure on the gateway host are fatal.

A client host can operate without `secrets.local.json`. A launch-time sync treats reconciliation failures as warnings so a cached harness package can still start. A first launch without a valid package cache fails.

## CLIProxyAPI jobs

The configuration job reads `tools/cliproxyapi/config.yaml.tmpl` and `tools/cliproxyapi/deployment.json`. When `secrets.local.json` exists, the job reads it. On the gateway host, it uses the file to render the server configuration. On a client host, it does not write the server configuration.

On the gateway host, the job writes the private file with mode `0600`:

- `~/.cli-proxy-api/config.yaml`

On a client host, the job never writes the server configuration.

Sync validates `tools/cliproxyapi/deployment.json` before reconciliation. It injects `listen.host` and `listen.port` into the generated gateway configuration.

The readiness job checks `client.baseUrl/models` without authentication on client hosts. The response must contain a non-empty `data` array. When the endpoint is unavailable, sync preserves the existing harness endpoint files.
The gateway host also receives `tools/cliproxyapi/panel.html` at `~/.cli-proxy-api/static/management.html`. Client hosts do not receive the panel.

Endpoint publication replaces every configured `${CLIPROXY_CLIENT_BASE_URL}` harness target as one transaction. Publication preserves the Codex-owned `[hooks.state]` and `[projects]` tables in `~/.codex/config.toml`. A write failure restores every target's previous content and mode.

The renderer parses and serializes YAML with PyYAML. It expands credential pools into native and compatibility profiles. The job writes generated files through a temporary file and an atomic rename.
## Installed runtime

Sync copies `sync/src/`, `sync/pyproject.toml`, and `sync/uv.lock` into a content-addressed release under `~/.local/share/agents/sync-releases/<releaseId>/`, then runs `uv sync --frozen --no-dev` there so the installed copy resolves its runtime dependencies. A `~/.local/share/agents/sync-current` symlink always points to the most recently published release. Generated wrappers execute this installed copy.

The `<releaseId>` is a SHA-256 digest computed over the runtime sources:

- Traverses `sync/src/` recursively, ordering directory entries in deterministic Unicode code-point order.
- Uses forward slashes (`/`) for all relative paths.
- Subdirectories are hashed as `dir:<relativePath>\n` before recursive descent.
- Regular files and symlinks pointing to regular files are hashed as `file:<relativePath>\n` followed by the file content bytes and a trailing `\n`. Directory symlinks are rejected.
- Appends the file contents of `sync/pyproject.toml` and `sync/uv.lock` in sequence.

Releases are staged in `~/.local/share/agents/sync-releases/.stage-<pid>-<nonce>` before the release is complete. A failed or aborted installation job cleans up its private staging directory in a `finally` block, leaving active and previous releases intact. During post-sync pruning, sync prunes completed, unreferenced releases and safely cleans up stale `.stage-<pid>-<nonce>` directories whose creating PID is no longer alive or is older than the install timeout, without deleting unrecognized user directories or active releases. Package operations similarly use unique per-operation staging (`staging-<pid>-<timestamp>`) and backup (`backup-<pid>-<timestamp>`) paths, rolling back to previous directory content on failure and cleaning up temporary backups only upon successful completion. Any legacy `~/.local/share/agents/sync/` mutable directory is removed after callers have migrated to `sync-current`.
## Extension hook state

Extension dependency hooks compute a content fingerprint (`fingerprintTree`) of their source directory to skip redundant installation steps when dependencies and sources have not changed:

- Produces a SHA-256 digest over the directory tree (or `"missing"` if the target path does not exist).
- Traverses directory entries in deterministic Unicode code-point (code-unit) order.
- Uses forward slashes (`/`) for all relative paths.
- Subdirectories are hashed as `dir:<relativePath>\n` before recursive descent.
- Regular files and symlinks to regular files are hashed as `file:<relativePath>\n` followed by file content bytes and a trailing `\n`.
- Broken symlinks are hashed as `broken:<relativePath>\n`. Symlinks pointing to directories are rejected with a diagnostic error.
- Ignored entries: skips `node_modules`, `.git`, hidden entries (names starting with `.`), and Python bytecode/caches (`__pycache__`, `*.pyc`, `*.pyo`).
## Managed CLIProxyAPI release

`tools/cliproxyapi/release.json` selects the GitHub repository, version, platform archive, binary, and checksum. Sync downloads an archive only when the cached executable or its receipt does not match the manifest.

The cache path has this form, where `<cache-home>` is `XDG_CACHE_HOME` or `~/.cache`:

```text
<cache-home>/github-tools/cliproxyapi/versions/<version>/<platform>-<architecture>/
```

Sync verifies the SHA-256 checksum, extracts only the named executable, writes a receipt, and generates a stable wrapper. The current manifest contains macOS ARM64 and Linux x86_64 assets.

Sync prepares the managed CLIProxyAPI binary and wrapper only on the gateway host. Client hosts remove a previously owned `cli-proxy-api` wrapper on the next sync.

## Launch behavior

Harness wrappers run a best-effort sync before launch. A failed sync, an active sync lock, or an unavailable repository does not block a cached harness package.

The launcher resolves the adapter's npm dist-tag and installs the resolved version into a versioned cache. The launcher keeps the current and previous known-good versions. If version resolution or a new package installation fails, the launcher uses the current valid cache. A first launch without a valid cache fails.

## Tool launchers

`TOOL_LAUNCHERS` in `sync/src/sync/core/tool_launchers.py` lists npm tools that sync launches like harnesses: a wrapper under `~/.local/bin/`, a versioned package cache, and a best-effort sync before launch. Tools have no harness home, instruction file, or skills.
