# Paseo daemon

[Paseo](https://github.com/getpaseo/paseo) drives coding agents (Pi, omp, Claude Code, Codex, OpenCode) from desktop, web, mobile, and CLI clients. Sync runs its daemon on the hosts listed in `tools/paseo/deployment.json` and publishes it to the tailnet only.

## How it is wired

| Piece | Owner | Where |
| --- | --- | --- |
| `paseo` command | Sync npm launcher (`@getpaseo/cli`, newest release on each launch) | `~/.local/bin/paseo` |
| Daemon service | Sync, on declared hosts | `paseo.service` (systemd user unit) |
| Nightly update | Sync, on declared hosts | `paseo-update.timer` runs `tools/paseo/update.py` |
| Tailnet exposure | The service's `ExecStartPost` / `ExecStopPost` | `tailscale serve` on HTTPS port 6767 |
| Daemon state and settings | The daemon and its clients | `~/.paseo/` (`config.json`, keypair, worktrees, logs) |

The daemon listens on `127.0.0.1:6767`. Tailscale Serve terminates TLS at `https://<host>.<tailnet>.ts.net:6767` and forwards to it, so nothing listens on a public or LAN interface. The unit sets these launch overrides, which take precedence over `config.json`:

- `PASEO_RELAY_ENABLED=false`: no outbound connection to Paseo's relay; clients reach the daemon only through the tailnet.
- `PASEO_WEB_UI_ENABLED=true`: the daemon serves the web client from the same origin.
- `PASEO_HOSTNAMES=.ts.net`: DNS-rebinding protection accepts the tailnet hostname.
- `PASEO_TRUSTED_PROXIES=loopback`: the daemon honors `X-Forwarded-Proto` from Tailscale Serve, so the web client reconnects over `wss://`.

Sync does not manage `~/.paseo/config.json`. The daemon and its clients write it (passwords, provider toggles, app settings), and overwriting it on every sync would discard those changes.

The launcher resolves the newest stable release when the service starts, but the running daemon keeps its version until it restarts. `paseo-update.timer` runs on the nightly update schedule (see [User services](sync/sync.md#user-services)). It compares the daemon's reported version with the newest release and restarts the service only when they differ and no agent is initializing or running. An unreadable status or agent listing never restarts. Inspect runs with `journalctl --user -u paseo-update.service`.

Control the daemon through systemd, not `paseo daemon start` or `paseo daemon stop`. A second supervisor started by hand owns `~/.paseo`, and the service's `paseo daemon run` then exits with `already_running` and restarts in a loop. `paseo reload` and `paseo daemon restart` are safe: they act on the existing supervisor.

## Set up a host

1. Add the host to `tools/paseo/deployment.json`, merge, and let sync install the service.
2. Enable omp, which Paseo ships disabled:

   ```sh
   paseo daemon config set agents '{"providers":{"omp":{"enabled":true}}}'
   paseo reload
   ```

   Providers are dynamic keys, so `config set` must replace the whole `agents.providers` object. Merge existing entries into the JSON first: `paseo daemon config get agents.providers`. Disable unused providers in the same object with `"<id>":{"enabled":false}`.
3. Choose a metadata model the gateway serves. Paseo matches its built-in candidates for workspace titles, branch names, and commit messages (a `haiku` model, then other small models) against enabled providers and can select models the gateway rejects. Select a small `cliproxy/...` model under **Settings → Host → Metadata → Manual**; the daemon stores it in `agents.metadataGeneration`.
4. Check the daemon and its providers:

   ```sh
   systemctl --user status paseo.service
   paseo provider ls
   tailscale serve status
   ```

Agents launched by the service inherit its `PATH`, which includes `~/.local/bin`, so they can orchestrate other agents with `paseo run` and `paseo agent`. An agent started this way becomes a subagent of its caller. Pi agents need this CLI because Paseo does not inject its tools into Pi; omp agents receive them natively.

The `paseo` skill in `skills/current/paseo/` ports Paseo's orchestration skills; [Track upstream ports](skills.md#track-upstream-ports) keeps it current. Do not install Paseo's own skills from **Settings** or `npx skills add`: that installer writes into `~/.claude/skills`, `~/.codex/skills`, and `~/.agents/skills` and refreshes them on every daemon start, conflicting with sync.

## Connect a client

- **Browser:** open `https://<host>.<tailnet>.ts.net:6767/`.
- **Phone or desktop app:** with Tailscale connected, choose **Settings → Add host → Direct connection**, enter `<host>.<tailnet>.ts.net` as the host and `6767` as the port, and turn **Use SSL** on.
- **CLI from another machine:** `paseo --host ssh://<host> ls` tunnels through SSH to the daemon's loopback port.

Do not pair through the relay (`paseo daemon pair --relay` or **Enable relay** in the app). The service keeps the relay off, and pairing through it would route clients through Paseo's servers.

Push notifications to the mobile app go through Expo's push service. Only the notification title and body take that path; agent traffic stays on the tailnet. Disable notifications in the app to avoid it.

## Remove a host

Remove the host from `tools/paseo/deployment.json`. Sync stops and disables `paseo.service`, and `ExecStopPost` removes the Tailscale Serve entry. `~/.paseo/` stays in place; delete it by hand to discard sessions and worktrees.
