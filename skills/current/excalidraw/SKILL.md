---
name: excalidraw
description: "Use when drawing, editing, or exporting Excalidraw diagrams on a live local canvas, not image generation."
license: AGPL-3.0-or-later
compatibility: Requires uv and bun. Screenshots and Mermaid need the canvas open in a browser tab.
metadata:
  author: anntnzrb
  upstream: https://github.com/yctimlin/mcp_excalidraw
---

# Excalidraw

Drive a live Excalidraw canvas from the shell. The CLI talks to a local canvas server; the user watches and edits the same canvas in a browser tab at the canvas URL. Edits from either side land in one scene.

## Public entrypoint

```sh
uv run --script <skill-dir>/scripts/cli.py <command> [args]
```

Set `<skill-dir>` to this skill directory. The wrapper forwards canvas commands unchanged to `bun x mcp-excalidraw-server@latest`, preserves their exit code, and attaches an idle watchdog to the canvas server. It answers `-h` and `--help` itself with wrapper help; use the `help` command for upstream help. NEVER call `bun x mcp-excalidraw-server` directly: commands that bypass the wrapper do not count as activity, so the watchdog may stop the server mid-task.

Live help is the only authority for commands, flags, and output shapes. This skill carries no command reference, so upstream releases need no edits here.

1. Run `help` to list commands and the exit-code contract.
2. Run `help <command>` before first use of a command this session.
3. Before building a diagram larger than a few shapes, read the guide upstream ships with the package. `install-skill --print-source` prints its directory as `source`; read `SKILL.md` and `references/cheatsheet.md` there. Ignore its MCP and REST sections and its `npx` spelling; use the entrypoint above.

Do not drive the canvas through browser automation; the CLI covers every operation.

## Server lifecycle

Any canvas command starts the server. A watchdog stops it after 30 minutes with no browser tab open, no scene change, and no wrapper command; `EXCALIDRAW_IDLE_TIMEOUT` overrides the seconds, and `0` disables it. Before stopping, the watchdog exports a non-empty scene to a `recovery/` directory under the state directory that `--help` names. Do not run `stop` yourself unless the user asks.

## Workflow

1. Run `status`. If the user wants to watch, give them the canvas URL.
2. Run `describe` before editing an existing scene. Target elements by `id`, never by coordinates.
3. The browser tab syncs user edits to the server after a short delay. Run `describe` again after the user says they changed something.
4. Create shapes with custom ids first, then arrows bound to those ids, in one batch call.
5. After each batch, run `describe` and fix overlap, truncated labels, and arrows crossing unrelated shapes before adding more.
6. When `status` reports an open browser tab, also take a screenshot to a temp file and view it.
7. Export to the path the user named when the diagram must outlive the server, and report the path.

## Durable rules

- The scene lives in server memory. Stopping the server empties it except for the watchdog's recovery export. Snapshots live in the same memory and do not survive a stop.
- After an idle stop, `import` the newest file from the recovery directory to continue the previous scene.
- Clearing, replacing on import, and restoring a snapshot overwrite the user's canvas. Save a snapshot first unless the user asked for a fresh canvas.
- When a command reports that a browser tab is required, ask the user to open the canvas URL, then retry. Do not open it yourself.
- `share` uploads the scene to excalidraw.com. Run it only when the user asks for a share link.
