# Sync reference

Sync reconciles the repository at `~/.config/agents` with harness homes and installed runtime state on macOS and Linux. The public entrypoint is `sync/src/sync/cli.py` (console script `sync`) and requires an explicit `uv` runner.

A gateway host has an OS hostname that matches `server.hostname` in `tools/cliproxyapi/deployment.json`. Every other supported host is a client host.

## Command syntax

| Invocation | Behavior |
| --- | --- |
| `uv run --project sync sync` | Runs a normal reconciliation |
| `uv run --project sync sync sync` | Runs the same normal reconciliation |
| `~/.local/share/agents/sync-current/.venv/bin/python -m sync.cli launch <name> -- <arguments>` | Syncs when the source is available, prepares the harness or tool package, and launches it |
| `~/.local/share/agents/sync-current/.venv/bin/python -m sync.cli update` | Fast-forwards the repository and reconciles a new commit; see [Background updates](#background-updates) |

Unknown commands and invalid arguments exit with status `2`. A manual sync exits with status `1` after a fatal reconciliation error.

## Reconciliation stages

A manual sync runs these stages in order:

1. Build and validate the sync plan and managed cleanup plan before any bootstrap effects. Malformed input fails without managed writes. Adapter-declared bootstraps run only when their adapter is enabled.
2. Remove stale top-level harness entries that earlier sync runs owned.
3. Install the sync runtime and reconcile source files, managed JSON configuration, shared assets, skills, and generated configuration.
4. On the gateway host, prepare managed tools from the committed release manifest.
5. Reconcile harness, tool, and managed-tool wrappers. Remove stale owned CLIProxyAPI wrappers on client hosts. Reconcile this host's [user services](#user-services).
6. Record managed harness entries.
7. Run package-bootstrap and extension-dependency hooks.

The process lock is `~/.local/share/agents/sync-managed/sync.lock`. A second manual sync reports the lock and exits with status `0` without changing targets. A manual sync requests cancellation after 15 minutes, allows up to 30 seconds for process-group cleanup and stage `finally` blocks, then exits with status `124` (forced termination cannot promise Python-level cleanup). Pre-launch sync is similarly bounded and falls back to the cached package with a warning on expiry; the launched harness session is never killed by an expired sync timer.

## File reconciliation

Sync compares file content and modes before replacement. An unchanged run leaves matching files in place (inode and mtime preserved). Secrets and new state files use mode `0600`; existing state files keep their regular-file mode; executable wrappers use `0755`. Subprocess stdout/stderr share a 10 MiB retained-byte limit; overflow terminates the process group and fails explicitly without parsing partial stdout. Package bootstrap publishes runtime settings only when every declared package resolves; partial failures leave settings bytes and mode untouched (an empty valid manifest deliberately publishes an empty list).

Directory jobs use one of two scopes:

- A tree job makes the destination tree match its source.
- A children job reconciles managed top-level entries inside an existing harness home, preserving unrelated top-level entries while making each managed subdirectory match its source.

Managed JSON configuration jobs copy the source file over the generated file and re-inject only the adapter-declared dot-paths from the previous file. See the [Harness adapter reference](harnesses.md#preserved-json-keys).

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

Endpoint publication replaces the `${CLIPROXY_CLIENT_BASE_URL}` and `${CLIPROXY_CLIENT_ORIGIN}` placeholders in every configured harness target as one transaction. Publication preserves the Codex-owned `[hooks.state]` and `[projects]` tables in `~/.codex/config.toml`. A write failure restores every target's previous content and mode.

The renderer parses and serializes YAML with PyYAML. It expands credential pools into native and compatibility profiles. Compatibility profiles marked `x-model-discovery: true` take their model list from the profile's `{base-url}/models` endpoint at render time, authenticated with the pool's first credential; the marker does not appear in the rendered file. Discovered entries are enriched into `models[]` records: upstream `name` and `context_length` fields map to `display-name` and `max-context-length`, and models.dev metadata (shared cache `~/.cache/agents/models-dev.json`, 24h TTL, refreshed lazily when stale) fills `display-name`, `max-context-length`, and `thinking.levels` (`["low","medium","high"]` for reasoning models, `["none"]` otherwise) when the upstream reports nothing, though when models.dev reports reasoning_options effort values for the model those values are preserved verbatim as thinking.levels (e.g. minimal/low/medium/high/xhigh) and the low/medium/high default applies only when the catalog marks reasoning without declaring options. A failed upstream lookup reuses the model list from the previously generated configuration; a failed catalog lookup leaves bare model names. The job writes generated files through a temporary file and an atomic rename.
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

`tools/cliproxyapi/release.json` selects the GitHub repository, version, platform archive, binary, and checksum. A `version` of `latest` resolves through the GitHub release redirect. Sync downloads an archive only when the cached executable or its receipt does not match the resolved release.

The cache path has this form, where `<cache-home>` is `XDG_CACHE_HOME` or `~/.cache`:

```text
<cache-home>/github-tools/cliproxyapi/versions/<version>/<platform>-<architecture>/
```

Sync verifies the release's SHA-256 checksum, extracts only the named executable, writes a receipt, and generates a stable wrapper.

Sync prepares the managed CLIProxyAPI binary and wrapper only on the gateway host. Client hosts remove a previously owned `cli-proxy-api` wrapper on the next sync.

## Launch behavior

Harness wrappers run a best-effort sync before launch. A failed sync, an active sync lock, or an unavailable repository does not block a cached harness package.

The launched harness runs in its own session. A wrapper that receives `SIGTERM` or `SIGHUP` forwards it to the harness's process group and exits with the harness, so a service manager stopping a wrapper also stops the harness instead of orphaning it.

The launcher resolves the adapter's npm dist-tag and installs the resolved version into a versioned cache. The launcher keeps the current and previous known-good versions. If version resolution or a new package installation fails, the launcher uses the current valid cache. A first launch without a valid cache fails.

A static release launcher resolves the adapter's manifest, verifies the archive SHA-256, and installs the version under the adapter's home-relative install root. It keeps the current and previous versions and reuses an installed version without re-downloading. When manifest resolution or installation fails, the launcher reuses the current cached install.

## User services

Sync installs and controls only the per-user services it declares: systemd user units on Linux and launch agents on macOS. It never touches system-level services. Declarations live in `sync/src/sync/core/services.py`; which ones apply depends on the host:

- Every host with a git checkout of the repository runs the [background updater](#background-updates).
- The CLIProxyAPI gateway host runs the gateway and, while its token is set, the [Funnel auth gateway](../cliproxyapi.md#expose-the-gateway-through-tailscale-funnel). Linux only.
- Hosts listed in `tools/amp-runner/deployment.json` run an Amp runner through the `amp` wrapper, identified by the short hostname. See the Amp harness README for why it starts from the home directory and serves the SSOT with an explicit `--dir`.

Reconcile rules:

- A declared unit or launch agent is authoritative. Sync writes it, replacing a hand-made file of the same name, and records it as owned in `sync-managed/services.json`. Services keep their pre-existing names so adoption replaces a hand-made service in place instead of starting a duplicate.
- Sync touches the service manager only when a unit's content changes: on Linux it reloads systemd, enables timers, and enables and restarts long-running services; on macOS it unloads and reloads the changed launch agent. A unit without an `[Install]` section is left to the timer that starts it. A unit that reads an env file embeds a digest of it, so changing only the env file (a token rotation) still restarts the service.
- A unit sync owned but no longer declares is disabled, stopped, and deleted. Units sync never owned are left alone.
- Every unit declares its own `PATH`, so services never depend on hand-made service-manager environment such as `~/.config/environment.d/`.
- Service reconcile is best-effort: a host without a user service manager gets a warning, not a failed sync.

User units keep running after logout only when lingering is enabled for the user, which is a machine-level setting outside this repository.

## Background updates

Every machine converges on `origin/main`: commit and push from any machine, and the others pick the change up on their own. Pushing stays manual; pulling and reconciling are automatic. The git hooks stay pure quality gates, so only commits that passed the `pre-push` tests reach `origin/main`.

Sync installs a per-user schedule — a systemd timer on Linux, a launch agent on macOS (see [User services](#user-services)) — that runs `sync update` every few minutes at idle CPU and I/O priority. Each run:

1. Skips the round if another sync holds the process lock; it never waits.
2. Fast-forwards only a clean checkout on `main`. Uncommitted tracked changes, another branch, or local commits missing from `origin/main` mean someone is working there: the checkout is left as is and nothing is merged, stashed, or reset. A failed fetch (offline) keeps the local checkout.
3. Reconciles only when the checked-out commit differs from the last one it reconciled successfully (`sync-managed/update.json`). A failed reconcile is retried on the next run.

The updater runs from the installed runtime, so a pulled change to sync's own code is reconciled once by the previous runtime; the new runtime takes over from the next run or launch.

The schedule needs no credentials because `origin` is public over HTTPS.

Inspect or trigger it:

```sh
systemctl --user start agents-update.service       # Linux: run now
journalctl --user -u agents-update.service -n 50   # Linux: recent runs
launchctl kickstart gui/$(id -u)/dev.agents.update # macOS: run now
tail -n 50 ~/Library/Logs/agents-update.log        # macOS: recent runs
```

## Tool launchers

`TOOL_LAUNCHERS` in `sync/src/sync/core/tool_launchers.py` lists npm tools that sync launches like harnesses: a wrapper under `~/.local/bin/`, a versioned package cache, and a best-effort sync before launch. Tools have no harness home, instruction file, or skills.
