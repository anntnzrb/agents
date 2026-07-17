---
name: hammerspoon
description: Inspect, configure, debug, or automate Hammerspoon, hs.*, Lua hotkeys, and macOS windows.
license: GPL-3.0-or-later
compatibility: Requires `uv`. Runtime introspection requires Hammerspoon running with `require("hs.ipc")` and the `hs` CLI installed. Docs/source lookup requires network unless cached.
metadata:
  author: anntnzrb
  allowed-tools: ""
---

# Hammerspoon

Treat Hammerspoon work as two connected systems:

- the running macOS automation runtime
- the persistent Lua config on disk

Prefer truth from the running instance first, then official docs, then upstream source/Spoons, then local config, then ecosystem corroboration.

## Entry point

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

## Evidence order

1. Runtime introspection via CLI (`status`, `eval`, `windows`, `apps`, `screens`, `hotkeys`, `spoons`, `config`)
2. Live official docs (`docs search`, `docs module`, `docs api`)
3. Live upstream source and Spoons (`source search`, `spoons search`, `spoons source`)
4. Local config files on disk
5. Ecosystem corroboration (Grep.app, GitHub code search) only after official/runtime sources

Avoid cloning Hammerspoon repos unless explicitly needed. Prefer the cached live fetches.

## Workflow

1. Inspect runtime state or live docs first
2. Inspect the relevant config files only as needed
3. Pick the right persistence target
4. Preview the intended change if a live preview is useful
5. Apply the persistent edit
6. Apply live when safe (reload config, evaluate Lua)
7. Verify both runtime state and file state
8. Call out Accessibility permission, MJConfigFile, or restart requirements explicitly

Default pattern: inspect → preview → apply → verify.

## Output discipline

- If the user asked for a report, note, patch file, or any other artifact at a specific path, create it before finalizing.
- Do not stop at an acknowledgement, plan, or partial progress update when the task asked for a concrete deliverable.
- After writing the requested artifact, summarize the result briefly.

## Runtime introspection

Default to `uv run --script <skill-dir>/scripts/cli.py` for Hammerspoon IPC. It wraps `hs` calls with quoting safety and structured output.

Prefer helper subcommands before custom Lua when they fit the task:

- `status` — Hammerspoon runtime health, version, config directory
- `doctor` — status plus Accessibility/MJConfigFile/CLI setup checks
- `eval` — execute Lua through `hs` and print the result
- `eval-file` — evaluate a Lua file safely without shell quoting
- `reload` — trigger `hs.reload()`
- `windows` — list all windows as JSON-safe summaries
- `apps` — list running applications
- `screens` — list displays
- `hotkeys` — list registered hotkeys
- `spoons` — list loaded Spoons
- `config` — show config directory path

Use raw `hs` CLI only when:

- debugging the helper itself
- the helper is unavailable
- a truly tiny one-off probe is simpler and there is no quoting risk

For reusable or multiline queries, prefer a temp Lua file plus `eval-file`.

## Live docs lookup

```text
uv run --script <skill-dir>/scripts/cli.py docs search <query>
uv run --script <skill-dir>/scripts/cli.py docs module <hs.module>
uv run --script <skill-dir>/scripts/cli.py docs api <symbol>
uv run --script <skill-dir>/scripts/cli.py docs refresh [--if-needed]
```

These fetch official Hammerspoon API docs from `hammerspoon.org/docs/` and cache them locally. Use `--json` for structured output with `source_url`, `signature`, `excerpt`, and line references.

Agents should navigate search results by exact symbols, module names, and source URLs.

## Live source and Spoons

```text
uv run --script <skill-dir>/scripts/cli.py source search <pattern>
uv run --script <skill-dir>/scripts/cli.py source fetch [--if-needed]
uv run --script <skill-dir>/scripts/cli.py spoon search <query>
uv run --script <skill-dir>/scripts/cli.py spoon source <name>
```

Source searches query the official Hammerspoon and Spoons GitHub repositories. Fetches are cached and refreshed only when stale or explicitly requested.

## Lua quality

```text
uv run --script <skill-dir>/scripts/cli.py lint <path>
uv run --script <skill-dir>/scripts/cli.py fmt --check <path>
uv run --script <skill-dir>/scripts/cli.py fmt --write <path>
uv run --script <skill-dir>/scripts/cli.py test <path>
uv run --script <skill-dir>/scripts/cli.py annotations status
uv run --script <skill-dir>/scripts/cli.py lsp-config print
```

These discover tools on PATH (`luacheck`, `stylua`, `busted`, `lua-language-server`). Missing tools return clear error messages with install guidance; they never silently succeed.

- `lint` — runs `luacheck` with Hammerspoon globals (`hs`, `spoon`).
- `fmt` — runs `stylua`, never formats implicitly.
- `test` — runs `busted` for pure Lua tests.
- `annotations` — reports whether Hammerspoon EmmyLua annotations appear generated.
- `lsp-config` — prints a suggested `.luarc.json` for Lua language server.

## Safe live-change pattern

- Make the intended file change first for persistent behavior.
- Then apply live only to preview or verify the persistent change.
- Prefer precise reloads:
  - `uv run --script <skill-dir>/scripts/cli.py reload`
  - `uv run --script <skill-dir>/scripts/cli.py eval-file <temp>.lua`
- Call out whether a change requires Accessibility permission grants, an `MJConfigFile` update, or a full Hammerspoon restart.
- If you test an ephemeral tweak before writing it, label it clearly as a preview and persist it before finishing.

## Guardrails

- Do not trust memory alone for Hammerspoon APIs; inspect runtime/docs/source.
- Do not assume a specific config layout, Spoon set, hotkey scheme, or config location; inspect first.
- Do not auto-install the `hs` CLI or Hammerspoon itself without explicit user request.
- Do not reload Hammerspoon after read-only inspection commands.
- Do not mutate the user's `init.lua` unless the task explicitly asks for persistent config changes.
- Do not format, lint, or fix config files unless the task asks.
- Prefer `uv run --script <skill-dir>/scripts/cli.py` over raw `hs` calls.
- Be explicit about risk when evaluating Lua in a running Hammerspoon.

## Resources

- `scripts/cli.py`: public dispatcher
- `scripts/hsctl.py`: internal engine for runtime, docs, source, and Lua tooling
