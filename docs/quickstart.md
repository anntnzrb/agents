# Set up agent configuration

This tutorial builds synced harness configuration, starts CLIProxyAPI on the configured gateway host, and verifies the shared model endpoint. Run it on the host whose name matches `server.hostname` in `assets/cliproxyapi/deployment.json`; client-only hosts use the safe readiness-gated path described in the [sync reference](sync.md).

Sync supports macOS and Linux only. The managed CLIProxyAPI release supports macOS on ARM64 and Linux on x86_64.

## Install the required commands

Install these commands:

- `bun` runs the sync application.
- `node` runs the npm-installed harness packages.
- `npm` installs harness packages on first launch.
- `git` clones the repository.
- `tar` extracts CLIProxyAPI.
- `openssl` generates local keys.
- `curl` and `jq` verify the gateway.

Confirm that each command is available:

```bash
bun --version
node --version
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

Edit the secrets file:

```bash
$EDITOR secrets.local.json
```

Replace every `replace-me` value. The credential pools contain upstream provider API keys. Use `weight: 1` when accounts have equal priority. Clients do not need client keys, and the management panel uses the static token committed in the template; the tailnet is the access boundary.

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

The process uses the listener from `assets/cliproxyapi/deployment.json`. Leave it running for the remaining steps.

## Refresh the model catalog

Return to the repository root and force a complete refresh:

```bash
bun ./sync/src/cli.ts sync --refresh-models
```

The forced refresh updates provider catalogs, models.dev metadata, and the live CLIProxyAPI catalog. A forced refresh fails instead of using stale network data.

## Verify the gateway

Query the model endpoint without authentication:

```bash
CLIPROXY_BASE_URL="$(jq -r '.client.baseUrl' assets/cliproxyapi/deployment.json)"
curl -fsS "$CLIPROXY_BASE_URL/models" | \
	jq -e '.data | type == "array" and length > 0'
unset CLIPROXY_BASE_URL
```

`jq` prints `true`. The exact model IDs depend on the current upstream catalogs and authenticated OAuth accounts.

## Start a harness

Open `sync/src/core/harness-adapters.ts`. Choose an adapter whose source directory exists and whose `platforms` field includes your host. Run the command in its `launcher.bin` field. Add harness arguments when needed.

The wrapper syncs the configuration, installs the cached harness package if needed, and opens the harness. The wrapper returns the harness exit status.

For later gateway operations, use [Operate CLIProxyAPI](cliproxyapi.md).
