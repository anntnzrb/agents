---
name: orca-cli
description: Use Orca CLI for worktrees, terminals, repos, artifacts, browser, handoffs, and structured multi-agent coordination.
---

# Orca CLI

This file is a discovery stub, not the usage guide. The `orca` binary serves the
full, version-matched guide so instructions cannot drift from the binary that runs
the commands.

Use Orca whenever its runtime is the source of truth:

- Operate Orca-managed worktrees, including child worktrees and `cardStatus`;
  control folder contexts, terminals, repos, automations, worktree comments, and
  the browser embedded inside Orca.
- Spawn Codex or Claude in a worktree, read/wait/send Orca terminals, or share
  HTML/Markdown and public artifact links.
- Perform a full ownership handoff when the user asks to hand off work, give it to
  another agent, or move it to another worktree without requesting supervision.
- Use structured orchestration when the user asks to supervise, monitor, or wait
  for agents; use threaded messages, blocking ask/reply flows, task dispatch,
  `worker_done` or escalation waits, task DAGs, decision gates, or coordinator loops.

Structured coordination requires real Orca runtime state. Never substitute a
non-Orca subagent tool. Use plain shell tools when Orca state does not matter. Use
Computer Use for browser windows, webviews, Orca app UI, or desktop UI outside
Orca's embedded browser.

## Resolve the CLI for this session

Choose the executable once and reuse it for every later command:

- If `ORCA_CLI_COMMAND` is set, use its value. Orca exports it for managed WSL
  sessions.
- Otherwise, if `ORCA_DEV_REPO_ROOT` is set in a dev checkout, use `orca-dev`.
- Otherwise, on Linux outside an Orca-managed terminal, use `orca-ide`. Never run
  bare `orca` there: it normally resolves to the GNOME Orca screen reader
  (`/usr/bin/orca`) and starts speech on the user's machine.
- Otherwise, use `orca`.

Below, `ORCA` is a placeholder for the resolved executable. Substitute it before
running commands; never create a shell variable or run `ORCA` literally. This is
portable across POSIX shells, PowerShell, and cmd.exe.

If the selected executable cannot run, report its exact error and stop. Never fall
through to another executable, which could silently target a different Orca build.

## Load the full guide before running Orca commands

```text
ORCA skills get orca-cli
```

Read the returned guide before choosing commands. It covers worktrees, handoffs,
terminals, automations, artifacts, the embedded browser, task creation and dispatch,
lifecycle preambles, `worker_done` authority, decision gates, and coordinator loops.

Never guess subcommands or flags from memory or from this stub. Confirm the app is
running with `ORCA status --json`; start it with `ORCA open --json` when needed.
Prefer `--json` for agent-driven calls.

## Legacy fallback

Use this fallback only when the selected binary explicitly reports that `skills
get` is an unknown command. Any other failure is not evidence of an older binary;
report it without changing executables.

For a confirmed pre-guide binary, use only this bounded, read-only bootstrap:

```text
ORCA status --json
ORCA worktree ps --json
ORCA terminal list --json
ORCA orchestration task-list --json
```

Tell the user that updating Orca restores the full guide through `ORCA skills get
orca-cli`. Ask before using any other command on an older binary; never invent a
command surface it may not support.

