# OpenCode plugins

## Manual continuation

`tmap/index.ts` uses the OpenCode v2 `context` hook. When the latest user message contains only a single
period, it changes that message to `Continue.` in model-visible context and adds a system-priority
notice to resume unfinished work. The notice also applies to tool-driven continuations until another
user message arrives. Persisted history keeps the original period; v2 does not expose the v1
synthetic/system fields on prompt admission. Messages with attachments are left unchanged.

OpenCode discovers every directory under the global `plugins/` directory. Only `cliproxy` is configured
explicitly, because it takes options. A configured plugin must be a directory; OpenCode drops a configured
file path with a warning.

## Automatic backgrounding

`autobg/tui.ts` is a CLI-only plugin, discovered from the global `plugins/` directory without a config entry. When a tool
call in a root session that is open in the terminal is still running after five seconds, it calls
`session.background`, the same action as the `session.background` keybind. OpenCode moves only blocking shell and
subagent jobs and later notifies the session with their full result. Headless clients such as `opencode run` and T3
Code do not load CLI plugins, so their sessions keep blocking tool calls.

## Validation

From a temporary copy of `harnesses/opencode/` (to avoid installing dependencies into the SSOT):

```sh
bun install --frozen-lockfile
bun test ./tests/plugins.test.ts
bun x --package typescript tsc --noEmit --strict --skipLibCheck --types node \
  --target esnext --module nodenext --moduleResolution nodenext \
  plugins/tmap/index.ts plugins/cliproxy/index.ts plugins/autobg/tui.ts
```

Tests exercise the continuation hook and model discovery with mocked HTTP responses, validate model
records against the v2 schema, check transform replay, recover from a gateway outage at startup, keep inventory on refresh failure, and
check the backgrounding threshold and session scoping with fake timers.

Run the same isolated test command as CI from the repository root:

```bash
uv run --script .github/scripts/ci.py harness opencode
```

The runner copies the owning harness into a temporary directory and uses the committed Bun lockfile. It does not change the installed harness or require provider credentials.
