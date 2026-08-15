# Quickstart

This guide produces synced harness configuration and a verified CLIProxyAPI executable.

## Install prerequisites

Install these commands before cloning the repository:

- `bun`
- `npm`
- `git`
- `tar`

The sync application supports macOS ARM64 and Linux x86_64 for CLIProxyAPI.

## Clone the repository

```bash
git clone https://github.com/anntnzrb/agents.git ~/.config/agents
cd ~/.config/agents
```

The repository must use `~/.config/agents` because generated wrappers call the sync entrypoint at that path.

## Provide local secrets

```bash
cp secrets.local.example.json secrets.local.json
chmod 600 secrets.local.json
$EDITOR secrets.local.json
```

Set both values:

- `CLIPROXY_API_KEY` authenticates local clients.
- `OPENCODE_GO_API_KEY` authenticates CLIProxyAPI to OpenCode Go.

Generate `CLIPROXY_API_KEY` with `openssl rand -hex 32`.

`secrets.local.json` is ignored by Git. Transfer it through a secure channel when you configure another machine.

## Run sync

```bash
bun ./sync/src/cli.ts
```

Sync performs these actions:

- generates harness configuration;
- downloads and verifies the pinned CLIProxyAPI release;
- writes `~/.local/bin/cli-proxy-api`;
- renders `~/.cli-proxy-api/config.yaml` with mode `0600`.

A manual sync warns when CLIProxyAPI is installed but not running.

## Authenticate CLIProxyAPI

On macOS, run:

```bash
cli-proxy-api --codex-login
```

On a headless Linux host, run:

```bash
cli-proxy-api --codex-device-login
```

Then restrict the generated OAuth file:

```bash
chmod 600 ~/.cli-proxy-api/codex-*.json
```

## Start CLIProxyAPI

Run CLIProxyAPI in the foreground:

```bash
cli-proxy-api
```

The managed wrapper passes `--config ~/.cli-proxy-api/config.yaml` automatically. Use your preferred process manager if the gateway must survive logout or reboot.

## Start a harness

```bash
pi
```

Managed harness wrappers run a best-effort sync before each launch. They continue with the cached harness package if launch-time sync cannot reach the network.
