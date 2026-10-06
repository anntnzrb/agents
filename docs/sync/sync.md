# Sync reference

Sync reconciles the repository at `~/src/agents` with harness homes and installed runtime state on macOS and Linux. The public entrypoint is `sync/src/sync/cli.py` (console script `sync`) and requires an explicit `uv` runner.

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
4. Reconcile harness and tool launch wrappers. Reconcile this host's [user services](#user-services).
5. Record managed harness entries.
6. Run package-bootstrap and extension-dependency hooks.

The process lock is `~/.local/share/agents/sync-managed/sync.lock`. A second manual sync reports the lock and exits with status `0` without changing targets. A manual sync requests cancellation after 15 minutes, allows up to 30 seconds for process-group cleanup and stage `finally` blocks, then exits with status `124` (forced termination cannot promise Python-level cleanup). Pre-launch sync is similarly bounded and falls back to the cached package with a warning on expiry; the launched harness session is never killed by an expired sync timer.

## File reconciliation

Sync compares file content and modes before replacement. An unchanged run leaves matching files in place (inode and mtime preserved). Secrets and new state files use mode `0600`; existing state files keep their regular-file mode; executable wrappers use `0755`. Subprocess stdout/stderr share a 10 MiB retained-byte limit; overflow terminates the process group and fails explicitly without parsing partial stdout. Package bootstrap publishes runtime settings only when every declared package resolves; partial failures leave settings bytes and mode untouched (an empty valid manifest deliberately publishes an empty list).

Directory jobs use one of two scopes:

- A tree job makes the destination tree match its source.
- A children job reconciles managed top-level entries inside an existing harness home, preserving unrelated top-level entries while making each managed subdirectory match its source.

Managed JSON configuration jobs copy the source file over the generated file and re-inject only the adapter-declared dot-paths from the previous file. See the [Harness adapter reference](harnesses.md#preserved-json-keys).

Recorded ownership limits cleanup to safe top-level names. Sync preserves unmanaged wrapper conflicts and reports each conflict.

## Missing sources and errors

Most missing source files and directories produce diagnostics but do not fail the run. Invalid committed configuration and hook failures are fatal.

A launch-time sync treats reconciliation failures as warnings so a cached harness package can still start. A first launch without a valid package cache fails.

## CLIProxyAPI endpoints

Sync validates `tools/cliproxyapi/deployment.json` before reconciliation.

The readiness job checks `client.baseUrl/models` without authentication. The response must contain a non-empty `data` array. When the endpoint is unavailable, sync preserves the existing harness endpoint files.

Endpoint publication replaces the `${CLIPROXY_CLIENT_BASE_URL}` and `${CLIPROXY_CLIENT_ORIGIN}` placeholders in every configured harness target as one transaction. Publication preserves the Codex-owned `[hooks.state]` and `[projects]` tables in `~/.codex/config.toml`. A write failure restores every target's previous content and mode.

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

Extension dependency hooks compute a content fingerprint (`fingerprint_tree` in `sync/src/sync/core/hook_state.py`) of their source directory to skip redundant installation steps when dependencies and sources have not changed:

- Produces a SHA-256 digest over the directory tree (or `"missing"` if the target path does not exist).
- Traverses directory entries in deterministic Unicode code-point (code-unit) order.
- Uses forward slashes (`/`) for all relative paths.
- Subdirectories are hashed as `dir:<relativePath>\n` before recursive descent.
- Regular files and symlinks to regular files are hashed as `file:<relativePath>\n` followed by file content bytes and a trailing `\n`.
- Broken symlinks are hashed as `broken:<relativePath>\n`. Symlinks pointing to directories are rejected with a diagnostic error.
- Ignored entries: skips `node_modules`, `.git`, hidden entries (names starting with `.`), and Python bytecode/caches (`__pycache__`, `*.pyc`, `*.pyo`).
## Launch behavior

Harness wrappers run a best-effort sync before launch. A failed sync, an active sync lock, or an unavailable repository does not block a cached harness package.

After preparing the harness, the wrapper process is replaced by the harness executable (`execve`). The harness keeps the wrapper's PID, session, process group, and controlling terminal, so terminal resizes, `^C`, job control, and a service manager's `SIGTERM` reach the harness directly, and its exit status is the wrapper's exit status. Captured subprocesses that sync runs itself (npm installs, smoke checks, hooks) still run in their own session so timeouts can kill the whole process group.

The launcher resolves the adapter's npm dist-tag and installs the resolved version into a versioned cache. The launcher keeps the current and previous known-good versions, plus any older version whose executable a running process still uses: a long-lived process such as the Amp runner keeps running the version it started from until it restarts, so an update never deletes it underneath that process. Running executables come from `/proc` on Linux and `lsof` on macOS; when they cannot be determined, pruning is skipped for that launch. Each install stages into `versions/.stage-<pid>-<token>` and removes it on exit; a stage survives only when its installer was killed, and the next prune removes it once that PID is no longer alive. If version resolution or a new package installation fails, the launcher uses the current valid cache. A first launch without a valid cache fails.

A static release launcher resolves the adapter's manifest, verifies the archive SHA-256, and installs the version under the adapter's home-relative install root. It keeps the current and previous versions and reuses an installed version without re-downloading. When manifest resolution or installation fails, the launcher reuses the current cached install.

## User services

Sync installs and controls only the per-user services it declares: systemd user units on Linux and launch agents on macOS. It never touches system-level services. Declarations live in `sync/src/sync/core/services.py`; which ones apply depends on the host:

- Legacy. Each T3 host (listed in `hosts` in `tools/t3/deployment.json`) runs `t3-refresh-models.timer`, which runs `tools/t3/t3ctl.py refresh-models` every 15 minutes with the installed runtime's Python. The gateway catalog changes with upstream discovery rather than with commits, so it runs on its own schedule instead of inside sync. See [T3 Code providers](../t3.md#providers). The same hosts run `t3-update.timer`, which runs `t3ctl.py auto-update` on the nightly schedule below. On macOS both jobs are the launch agents `dev.agents.t3-refresh-models` and `dev.agents.t3-update`. See [T3 Code automatic updates](../t3.md#automatic-updates).
- Hosts listed in `tools/amp-runner/deployment.json` run an Amp runner through the `amp` wrapper, identified by the short hostname. See the Amp harness README for why it starts from the home directory and serves the SSOT with an explicit `--dir`. On Linux the runner starts with `--desktop`, which gives its threads a private headless virtual desktop and needs `labwc`, `wlr-randr`, and `ffmpeg` on the service `PATH`; without them the runner still serves threads and logs that desktop sharing is unavailable. On macOS `--desktop` would share the Mac's real screen, so the launch agent omits it. Check readiness with `amp runner desktop status`. The same hosts run `amp-runner-update.timer`, which runs `tools/amp-runner/update.py` on the nightly schedule below: the wrapper installs new releases on launch, but the running runner keeps its version until it restarts, so this script restarts it onto the newest cached release when it is behind and idle. It treats any thread event in the runner log within the last 15 minutes, or a thread whose last agent state is not `idle` within the last 2 hours, as busy, and never restarts when the log is unreadable. On macOS the job is the `dev.agents.amp-runner-update` launch agent and restarts the runner with `launchctl kickstart -k`.
- The nightly update jobs run hourly from 03:00 to 05:00 local time. On Linux they add up to 20 minutes of random delay and catch up after downtime (`Persistent=true`); launchd runs a missed calendar slot once on wake. An attempt that finds the server current or busy does nothing, so a busy hour leaves the later ones. Inspect runs with `journalctl --user -u <name>-update.service` on Linux or `~/Library/Logs/<name>-update.log` on macOS.
- Adding a host to a service's deployment file is the whole rollout: the host's next sync installs that service's units or launch agents, and removing the host prunes them.
- Hosts listed in `tools/cache-gc/deployment.json` run `cache-gc.timer` (the `dev.agents.cache-gc` launch agent on macOS) on the nightly schedule, at idle CPU and I/O priority on Linux. It runs `tools/cache-gc/cache_gc.py`, which trims the npm, uv, and bun caches and stale `/tmp` scratch. See [Cache sweeper](../cache-gc.md).
- Hosts listed in `tools/paseo/deployment.json` run `paseo.service`, the Paseo daemon on loopback, and publish it to the tailnet with `tailscale serve` on HTTPS port 6767. Their nightly `paseo-update.timer` restarts the daemon onto a newer release when no agent is mid-turn. See [Paseo daemon](../paseo.md).

Reconcile rules:

- A declared unit or launch agent is authoritative. Sync writes it, replacing a hand-made file of the same name, and records it as owned in `sync-managed/services.json`. Services keep their pre-existing names so adoption replaces a hand-made service in place instead of starting a duplicate.
- Sync touches the service manager only when a unit's content changes: on Linux it reloads systemd, enables timers, and enables and restarts long-running services; on macOS it unloads and reloads the changed launch agent. A unit without an `[Install]` section is left to the timer that starts it.
- A unit sync owned but no longer declares is disabled, stopped, and deleted. Units sync never owned are left alone.
- Every unit declares its own `PATH`, so services never depend on hand-made service-manager environment such as `~/.config/environment.d/`.
- Service reconcile is best-effort: a host without a user service manager gets a warning, not a failed sync.

User units keep running after logout only when lingering is enabled for the user, which is a machine-level setting outside this repository.

## Background updates

Every machine converges on `origin/main`: commit and push from any machine, and the others pick the change up on their own. Pushing stays manual; pulling and reconciling are automatic. The git hooks stay pure quality gates, so only commits that passed the `pre-push` tests reach `origin/main`.

The machine configuration schedules `sync update` every few minutes on each host; this repository installs no updater of its own. Each run:

1. Skips the round if another sync holds the process lock; it never waits.
2. Fast-forwards only a clean checkout on `main`. Uncommitted tracked changes, another branch, or local commits missing from `origin/main` mean someone is working there: the checkout is left as is and nothing is merged, stashed, or reset. A failed fetch (offline) keeps the local checkout. Each of these cases logs a `sync: warning: update: …` line naming the blocker (the changed files, the branch, or the local and upstream commit counts), so a host that stops converging shows why in its updater log; an up-to-date run logs nothing.
3. Reconciles only when the checked-out commit differs from the last one it reconciled successfully (`sync-managed/update.json`). A failed reconcile is retried on the next run.

The updater runs from the installed runtime, so a pulled change to sync's own code is reconciled first by the previous runtime, which cannot know about anything the new code adds, such as a new harness adapter. When that reconcile installs a new runtime, the updater does not record the commit as synced and logs `update: sync runtime changed; reconciling again on the next run`; the next run reconciles the same commit with the new runtime.

The schedule needs no credentials because `origin` is public over HTTPS.

Inspect or trigger it through the machine configuration's scheduler; see its source-checkout documentation for unit names and logs.

A host stuck behind `origin/main` repeats the same warning on every run. Commit and push the local work, or discard it, and the next run fast-forwards.

## Tool launchers

`TOOL_LAUNCHERS` in `sync/src/sync/core/tool_launchers.py` lists npm tools that sync launches like harnesses: a wrapper under `~/.local/bin/`, a versioned package cache, and a best-effort sync before launch. Tools have no harness home, instruction file, or skills.

Sync copies `tools/mcporter/mcporter.jsonc` to `~/.mcporter/mcporter.json` and `tools/summarize/config.json` to `~/.summarize/config.json`, replacing the endpoint placeholders in the second file. `_config_jobs` in `sync/src/sync/core/plan.py` declares these jobs.
