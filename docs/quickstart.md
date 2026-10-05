# Set up agent configuration

Follow this tutorial to configure and synchronize agent environments, launch wrappers, and harness configuration files.

Sync supports macOS and Linux.

## Install the required commands

Sync itself requires Python 3.12+ via `uv`. Managed packages and extensions additionally use `bun`, `node`, and `npm`.

Install `uv`, `python3`, `bun`, `node`, `npm`, `git`, `tar`, `curl`, and `jq`.

Confirm that each command is available:

```bash
uv --version
python3 --version
bun --version
node --version
npm --version
git --version
tar --version
curl --version
jq --version
```

Each command prints its version.

## Clone the repository

Clone the repository at the path that sync expects:

```bash
git clone https://github.com/anntnzrb/agents.git ~/src/agents
cd ~/src/agents
```

The shell is now in `~/src/agents`.

Enable the repository's [Git hooks](../.githooks/README.md), which run the sync quality gates and keep commits off `main`:

```bash
git config --local core.hooksPath .githooks
```

## Configure shared environment variables

Copy the shared environment template if `.env` does not exist yet, restrict access, and edit the file:

```bash
if [ ! -e .env ]; then cp .env.example .env; fi
chmod 600 .env
$EDITOR .env
```

The repository root `.env` provides default environment variables that `sync` forwards to child processes of launched harnesses. Parent-process environment variables override values in this file.

## Generate the runtime files

Run sync from the repository root:

```bash
uv run --project sync sync
```

Sync creates the self-hosted runtime link, harness configuration files, tool configs, and launch wrappers in `~/.local/bin/`.

## Verify gateway connectivity

Sync checks `client.baseUrl` in `tools/cliproxyapi/deployment.json` before publishing endpoint templates to harnesses. Query the model endpoint directly:

```bash
CLIPROXY_BASE_URL="$(jq -r '.client.baseUrl' tools/cliproxyapi/deployment.json)"
curl -fsS "$CLIPROXY_BASE_URL/models" | \
	jq -e '.data | type == "array" and length > 0'
unset CLIPROXY_BASE_URL
```

`jq` prints `true` when the external gateway is reachable and responding.

## Start a harness

Choose an adapter whose source directory exists under `harnesses/` and whose `platforms` field includes your host. Read its `launcher.bin` value in `sync/src/sync/core/harness_adapters.py`, then run that wrapper command (for example `codex`, `pi`, or `omp`).

The wrapper runs sync, prepares the cached harness package, forwards arguments, and returns the harness exit status.
