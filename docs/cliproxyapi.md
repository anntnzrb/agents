# CLIProxyAPI

CLIProxyAPI provides one local API for ChatGPT subscription access and OpenCode Go.

## Managed artifacts

| Artifact | Path |
|---|---|
| Portable config template | `assets/cliproxyapi.yaml.tmpl` |
| Release pin and checksums | `assets/cliproxyapi.release.json` |
| Local secrets | `secrets.local.json` |
| Generated config | `~/.cli-proxy-api/config.yaml` |
| OAuth runtime files | `~/.cli-proxy-api/codex-*.json` |
| Managed command | `~/.local/bin/cli-proxy-api` |

Sync supports the official macOS ARM64 and Linux x86_64 release assets pinned in the manifest. It downloads from GitHub, verifies SHA-256, extracts only `cli-proxy-api`, and caches the result.

## Configure secrets

Copy the example and set both values:

```bash
cp secrets.local.example.json secrets.local.json
chmod 600 secrets.local.json
$EDITOR secrets.local.json
bun ./sync/src/cli.ts
```

Never commit `secrets.local.json` or OAuth files.

## Authenticate ChatGPT

Use browser OAuth on macOS:

```bash
cli-proxy-api --codex-login
```

Use device login on a headless Linux host:

```bash
cli-proxy-api --codex-device-login
```

Do not copy one active refresh token between two running gateways. Stop the old gateway before transferring OAuth state, or authenticate again on the new host.

## Run the gateway

```bash
cli-proxy-api
```

The wrapper supplies the generated config path. CLIProxyAPI listens on `127.0.0.1:8317`. Sync does not install a service. Use launchd, systemd, tmux, or another process manager when you need background operation.

A manual sync prints this warning when the endpoint is unavailable:

```text
sync: warning: CLIProxyAPI is installed but not running; start it with: cli-proxy-api
```

## Verify the gateway

```bash
KEY=$(jq -r .CLIPROXY_API_KEY secrets.local.json)
curl -fsS http://127.0.0.1:8317/v1/models \
  -H "Authorization: Bearer $KEY" |
  jq -r '.data[].id'
```

Expected model names include `gpt-5.6-luna` and `go/gpt-5.6-luna`.
