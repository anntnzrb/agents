# Set up agent configuration

This tutorial builds synced harness configuration, starts CLIProxyAPI, and verifies the local model endpoint.

The managed CLIProxyAPI release supports macOS on ARM64 and Linux on x86_64. The harness adapters also support Windows, but the release manifest has no Windows CLIProxyAPI asset.

## Install the required commands

Install these commands:

- `bun` runs the sync application.
- `npm` installs harness packages on first launch.
- `git` clones the repository.
- `tar` extracts CLIProxyAPI.
- `openssl` generates local keys.
- `curl` and `jq` verify the gateway.

Confirm that each command is available:

```bash
bun --version
npm --version
git --version
tar --version
openssl version
curl --version
jq --version
```

Each command prints its version or help text.

## Clone the repository

Clone the repository at the path that sync expects:

```bash
git clone https://github.com/anntnzrb/agents.git ~/.config/agents
cd ~/.config/agents
```

The working directory is now `~/.config/agents`.

## Add local secrets

Copy the example and restrict access to the new file:

```bash
cp secrets.local.example.json secrets.local.json
chmod 600 secrets.local.json
```

Generate a management key and at least one client key:

```bash
openssl rand -hex 32
```

Run the command again for each key. Then edit the secrets file:

```bash
$EDITOR secrets.local.json
```

Replace every `replace-me` value. The credential pools contain upstream provider API keys. Use `weight: 1` when accounts have equal priority.

The repository ignores `secrets.local.json`. Keep the file out of Git and transfer it only through an encrypted channel.

## Generate the runtime files

Run sync from the repository root:

```bash
bun ./sync/src/cli.ts
```

The first run downloads the pinned CLIProxyAPI archive, verifies its SHA-256 checksum, and generates the runtime files. The run can warn that CLIProxyAPI is not running yet.

Confirm that sync created the main artifacts:

```bash
test -x ~/.local/bin/cli-proxy-api
test -f ~/.cli-proxy-api/config.yaml
test -f ~/.local/share/agents/model-catalog/catalog.json
```

All three commands exit with status `0`.

## Authenticate a ChatGPT account

On macOS, start browser authentication:

```bash
cli-proxy-api --codex-login
```

On a headless Linux host, start device authentication:

```bash
cli-proxy-api --codex-device-login
```

After authentication, restrict the generated OAuth file:

```bash
chmod 600 ~/.cli-proxy-api/codex-*.json
```

## Start CLIProxyAPI

Start the gateway in a separate terminal:

```bash
cli-proxy-api
```

The process listens on `127.0.0.1:8317`. Leave it running for the remaining steps.

## Refresh the model catalog

Return to the repository root and force a complete refresh:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

The forced refresh updates provider catalogs, models.dev metadata, and the live CLIProxyAPI catalog. A forced refresh fails instead of using stale network data.

## Verify the gateway

Read the client key without printing it, then query the model endpoint:

```bash
CLIPROXY_KEY="$(jq -r '.CLIPROXY_CLIENT_API_KEYS[0]' secrets.local.json)"
curl -fsS http://127.0.0.1:8317/v1/models \
	-H "Authorization: Bearer $CLIPROXY_KEY" | \
	jq -e '.data | type == "array" and length > 0'
unset CLIPROXY_KEY
```

`jq` prints `true`. The exact model IDs depend on the current upstream catalogs and authenticated OAuth accounts.

## Start a harness

Start Pi:

```bash
pi
```

The wrapper syncs the configuration, installs the cached harness package if needed, and opens Pi. Codex, OpenCode, and OMP use the `codex`, `opencode`, and `omp` commands.

For later gateway operations, use [Operate CLIProxyAPI](cliproxyapi.md).
