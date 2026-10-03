# Cache sweeper

Sync's launchers resolve the newest release on every launch. The versioned caches sync owns prune themselves (see [Launch behavior](sync/sync.md#launch-behavior)), but the package managers underneath them keep every download: npm's content cache, bun's install cache, and uv's archive cache only grow. Agents also leave scratch in `/tmp`. `tools/cache-gc/cache_gc.py` trims those and nothing else.

## What it removes

| Step | Command | Guard |
| --- | --- | --- |
| npm | `npm cache clean --force` | Runs only while holding every `npm-tools/<tool>/lock`; a launcher mid-install makes it skip npm for that run |
| uv | `uv cache prune` | uv keeps entries in use and waits on its own cache lock |
| bun | `bun pm cache rm` | Runs from an empty temporary package, which `bun pm` requires |
| scratch | Deletes top-level `/tmp` entries this user owns whose newest modification is older than 7 days | Never touches sockets, `*.lock` files, other users' entries, or names starting with `.`, `tmux-`, `zellij-`, `systemd-private-`, `ssh-`, `com.apple.`, `launchd-`, `nix-` |

Harness homes stay out of scope: sessions, browser downloads, runtimes, and anything under `~/.omp`, `~/.pi`, `~/.codex`, `~/.claude`, `~/.hermes`, or `~/.t3`. Every step is best-effort; a failing step is logged and the rest still run.

The first launch after a sweep re-downloads that tool's dependencies. That cost is paid once per tool per night at most.

## Operate

`tools/cache-gc/deployment.json` lists the hosts. Sync installs `cache-gc.timer` on Linux and the `dev.agents.cache-gc` launch agent on macOS, on the nightly schedule in [User services](sync/sync.md#user-services). Adding or removing a host and running sync is the whole rollout.

```sh
# Preview without deleting anything
~/.local/share/agents/sync-current/.venv/bin/python ~/.config/agents/tools/cache-gc/cache_gc.py --dry-run

# Run now (Linux)
systemctl --user start cache-gc.service
journalctl --user -u cache-gc.service -n 20

# Run now (macOS)
launchctl kickstart gui/$(id -u)/dev.agents.cache-gc
tail ~/Library/Logs/cache-gc.log
```

## Validate a change

```sh
uvx ruff==0.16.10 check --config sync/pyproject.toml tools/cache-gc
uvx --python 3.14 --with pytest==9.1.1 basedpyright==1.40.1 -p tools/cache-gc
uvx --python 3.14 pytest==9.1.1 tools/cache-gc/tests -q
```

CI runs the same checks in `repository-checks`.
