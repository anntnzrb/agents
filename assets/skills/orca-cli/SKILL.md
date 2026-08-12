---
name: orca-cli
description: Use Orca CLI for worktrees, terminals, repos, artifacts, browser, handoffs, and structured multi-agent coordination.
---

# Orca CLI

Discovery stub, not usage guide. The `orca` binary serves the full version-matched guide, preventing instruction drift from the running binary.

## When to use

Use Orca when its runtime is source of truth:
- Orca-managed worktrees, child worktrees, `cardStatus`; folder contexts, terminals, repos, automations, worktree comments, embedded browser.
- Spawn Codex or Claude in worktrees; read, wait for, or send through Orca terminals; share HTML/Markdown and public artifact links.
- User requests full ownership handoff to another agent/worktree without requesting supervision.
- User requests agent supervision, monitoring, or waiting: use structured orchestration (threaded messages, blocking ask/reply, task dispatch, `worker_done`/escalation waits, task DAGs, decision gates, coordinator loops).

Structured coordination requires real Orca runtime state: NEVER substitute a non-Orca subagent tool. Use plain shell tools when Orca state does not matter. Use Computer Use for browser windows, webviews, Orca app UI, or desktop UI outside Orca's embedded browser.

## Resolve executable

Choose once per session; reuse for every command:
1. `ORCA_CLI_COMMAND` set → its value.
2. Else `ORCA_DEV_REPO_ROOT` set in a dev checkout → `orca-dev`.
3. Else Linux outside an Orca-managed terminal → `orca-ide`; NEVER bare `orca` there (`/usr/bin/orca` is normally GNOME Orca screen reader and starts speech).
4. Else → `orca`.

`ORCA` below means the resolved executable. Substitute it before execution; NEVER create a shell variable or run `ORCA` literally. Portable across POSIX shells, PowerShell, and cmd.exe.

Selected executable cannot run → report its exact error and stop; NEVER fall through to another executable (it may target a different Orca build).

## Guide required

Before any Orca command, run:

```text
ORCA skills get orca-cli
```

Read the returned guide before selecting commands. It covers worktrees, handoffs, terminals, automations, artifacts, embedded browser, task creation/dispatch, lifecycle preambles, `worker_done` authority, decision gates, and coordinator loops.

NEVER guess subcommands or flags from memory or this stub. Confirm app running with `ORCA status --json`; when needed, start it with `ORCA open --json`. Prefer `--json` for agent-driven calls.

## Legacy fallback

Use fallback ONLY if the selected binary explicitly reports `skills get` as an unknown command. Any other failure is not evidence of an older binary: report it without changing executables.

For a confirmed pre-guide binary, use only this bounded, read-only bootstrap:

```text
ORCA status --json
ORCA worktree ps --json
ORCA terminal list --json
ORCA orchestration task-list --json
```

Tell the user updating Orca restores the full guide through `ORCA skills get orca-cli`. Ask before any other command on an older binary; NEVER invent an unsupported command surface.
