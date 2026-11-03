# Set up agent configuration

Follow this tutorial to configure and synchronize agent environments, launch wrappers, and harness configuration files.

Sync supports macOS and Linux.

## Install the required commands

Sync requires Bun. Managed packages and extensions additionally use Node.js and npm; skills and harness Python environments use `uv`.

Install `bun`, `node`, `npm`, `uv`, `git`, `tar`, `curl`, and `jq`.

Confirm that each command is available:

```bash
bun --version
node --version
npm --version
uv --version
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

Enable the repository's [Git hooks](../.githooks/README.md), which run the sync quality gates and selected repository checks:

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
bun run --cwd sync sync
```

Sync installs its own runtime under `~/.local/share/agents/`, publishes harness configuration files and tool configs, and generates launch wrappers in `~/.local/bin/`.

## Verify gateway connectivity

Sync checks `gateway.base_url` in `agents.toml` before publishing endpoint templates to harnesses. Query the model endpoint directly:

```bash
base_url="$(bun -e 'console.log(Bun.TOML.parse(await Bun.file("agents.toml").text()).gateway.base_url)')"
curl -fsS "$base_url/models" | jq -e '.data | type == "array" and length > 0'
```

`jq` prints `true` when the external gateway is reachable and responding.

## Start a harness

Choose an adapter whose source directory exists under `harnesses/` and whose `platforms` field includes your host. Read its launcher in `sync/src/domain/HarnessAdapters.ts`, then run that wrapper command (for example `codex`, `pi`, or `omp`).

The wrapper hands the command to the installed sync runtime, which launches the cached harness package with your arguments; a first launch also syncs and installs the package. The wrapper exits with the harness exit status.
