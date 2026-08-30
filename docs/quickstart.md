# Set up agent configuration

Follow this tutorial on the gateway host, whose name matches `server.hostname` in `tools/cliproxyapi/deployment.json`. It creates the generated files, starts CLIProxyAPI, verifies the model endpoint, and starts a harness.

The sync engine also runs on client hosts. A client host needs the native `agentium` binary and the local `~/.config/agents/` configuration tree. It does not need the local sync source, `secrets.local.json`, Node, npm, Git, GitHub CLI, tar, or uv to run sync. See the [Sync reference](sync/sync.md#native-binary-runtime) for client host runtime details.

Sync supports macOS and Linux. The managed CLIProxyAPI release supports macOS on ARM64 and Linux on x86_64.

## Install gateway setup commands

The native sync engine is distributed as the `agentium` binary. This tutorial also uses Git to clone the repository and `curl` and `jq` to verify the gateway. Bun remains necessary only if you launch harnesses or extensions that execute npm packages or Bun scripts.

Confirm that each command is available:

```bash
agentium --version
git --version
curl --version
jq --version
```

Each command prints its version.

## Run sync on a client host

Install `agentium` on a client host (on `PATH`, at `~/.local/share/agentium/bin/agentium`, or via `AGENTIUM_BIN`) and keep the local `~/.config/agents/` configuration tree available. Do not install Node, npm, Git, GitHub CLI, tar, or uv for the sync engine.

Run a generated harness wrapper, or invoke the binary directly:

```bash
agentium launch <name> -- <arguments>
```

A client host can omit `secrets.local.json`. A harness package or configured hook may have separate runtime requirements.

## Clone the repository

Clone the repository at the path that sync expects:

```bash
git clone https://github.com/anntnzrb/agents.git ~/.config/agents
cd ~/.config/agents
```

The shell is now in `~/.config/agents`.

## Configure shared environment variables

Copy the shared environment template if `.env` does not exist yet, restrict access, and edit the file:

```bash
if [ ! -e .env ]; then cp .env.example .env; fi
chmod 600 .env
$EDITOR .env
```

The repository root `.env` provides default environment variables that `sync` forwards to child processes of launched harnesses. Parent-process environment variables override values in this file.

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

Replace every `replace-me` value with an upstream provider API key. Use `weight: 1` when accounts have equal priority. The [CLIProxyAPI reference](cliproxyapi.md#local-secrets) describes the file shape.

The repository ignores `secrets.local.json`. Keep the file out of Git and transfer it through an encrypted channel.

## Generate the runtime files

Run sync from the repository root:

```bash
agentium sync
```

The first gateway-host run may download the pinned CLIProxyAPI archive. Sync verifies its SHA-256 checksum and generates the runtime files. Sync can warn that CLIProxyAPI is not running yet.

Confirm that sync created the main artifacts:

```bash
test -x ~/.local/bin/cli-proxy-api
test -f ~/.cli-proxy-api/config.yaml
test -f ~/.local/share/agentium/model-catalog/catalog.json
```

Each test exits with status `0` when the required path exists with the expected type and permissions.

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

The process uses the listener from `tools/cliproxyapi/deployment.json`. Keep it running for the remaining steps.

## Refresh the model catalog

Return to the repository root and force a complete refresh:

```bash
agentium sync --refresh-models
```

The forced refresh updates provider catalogs, models.dev metadata, and the live CLIProxyAPI catalog. It fails instead of using stale network data.

## Verify the gateway

Query the model endpoint without authentication:

```bash
CLIPROXY_BASE_URL="$(jq -r '.client.baseUrl' tools/cliproxyapi/deployment.json)"
curl -fsS "$CLIPROXY_BASE_URL/models" | \
	jq -e '.data | type == "array" and length > 0'
unset CLIPROXY_BASE_URL
```

`jq` prints `true`. Model IDs depend on the current upstream catalogs and authenticated OAuth accounts.

## Start a harness

Choose an adapter whose source directory exists under `harnesses/` and whose `platforms` field includes your host. Read its `launcher.bin` value in `sync/crates/app-core/src/harness_adapters.rs`, then run that wrapper command.

The wrapper runs sync, prepares the cached harness package, forwards your arguments, and returns the harness exit status.

For later gateway operations, use [Operate CLIProxyAPI](cliproxyapi.md).
