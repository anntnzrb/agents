# Pharos

Pharos nudges the agent toward focused Bash commands without blocking or rewriting tool calls.
The preferences live in [`index.ts`](index.ts).

The extension assigns a named prompt section before each agent run when `bash` is active.
It removes that section when `bash` is inactive and leaves other prompt sections and tool guidance unchanged.
Repeated runs do not accumulate copies. It has no commands, settings, subprocesses, or session state.

## Validate

From the repository root, run the callback tests with Pi's installed host packages:

```sh
T=$(mktemp -d)
cp -R harnesses/pi/agent/extensions/pharos "$T/pharos"
ln -s ~/.pi/agent/extensions/node_modules "$T/node_modules"
(cd "$T" && bun test pharos/)
git diff --check
```

For a live check in a temporary project containing text files and JSON, load the source explicitly:

```sh
# Set this absolute path from the repository root before changing directories.
EXT="$PWD/harnesses/pi/agent/extensions/pharos/index.ts"
pi --no-extensions -e "$EXT" \
	--no-session --mode json -p --tools bash,read \
	"Find files containing the literal TODO, list TypeScript paths, inspect the JSON keys, and read one source file."
```

If your model provider comes from an extension, load that provider explicitly with another `-e` argument.
Keep captured JSONL output outside the searched project so searches do not match their own transcript.

Inspect the JSONL prompt section and actual tool calls, not the agent's description of its choices.
Check that the agent uses focused search and JSON commands while still using `read` for file contents.
Model choices are not deterministic; the callback tests verify injection, not compliance.

After sync publishes the extension, run `/reload` in existing Pi sessions.
