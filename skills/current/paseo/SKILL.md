---
name: paseo
description: "Use when delegating to Paseo subagents, handing off tasks, getting second opinions, or setting Paseo heartbeats."
license: AGPL-3.0-or-later
---

# Paseo

Paseo is a daemon that runs coding agents in workspaces. Agents it launches can launch and steer other agents. Drive it through the injected Paseo tools when they are available, otherwise through the `paseo` CLI. Pi agents receive no injected tools; use the CLI.

Paseo sets `PASEO_AGENT_ID` in every agent it launches. An agent you create from that session becomes your subagent; omit the workspace to share your files.

## Choose settings before delegating

1. List agent profiles with `list_profiles`, or `paseo daemon config get daemon.agentProfiles --json` from the CLI, and read every profile's notes. Pick a profile the user named, else the one whose notes best fit the work.
2. Materialize it: `provider/model` into the provider value, mode, thinking option, and features into the launch settings. There is no profile parameter.
3. With no fitting profile, discover options with `paseo provider ls` and `paseo provider models <provider>`. Tell the user which fallback you chose.
4. Prefer a different model family from your own for reviews and second opinions.

## Common calls

```bash
paseo run -d --title "<title>" --provider <provider>/<model> [--thinking <id>] "<prompt>"
paseo run -d --new-workspace worktree --worktree-mode branch-off --new-branch <branch> --base origin/main --provider <provider>/<model> "<prompt>"
paseo send <agent-id> "<follow-up>"
paseo agent wait <agent-id> --timeout <seconds>
paseo logs <agent-id>
paseo ls
paseo archive <agent-id>
paseo heartbeat create --cron "*/10 * * * *" --expires-in 2h "<prompt>"
paseo heartbeat delete <heartbeat-id>
```

- Pass `--base origin/main`, not `main`; Paseo fetches remote refs, while local `main` can be stale.
- Give a worktree when parallel workers edit files; share the workspace for read-only workers.
- Discover other commands with `paseo <command> --help`.

## Waiting

- Agents routinely take 10 to 30 minutes. Injected tools notify you when a subagent finishes; do not poll `list_agents` or `get_agent_status`.
- From the CLI, block with `paseo agent wait` only when your next step needs the result; otherwise keep working.

## Heartbeats

A heartbeat re-prompts the same agent on a cron cadence and keeps its conversation. Use one for unattended goals: state the next small step, the checks to run each time, and that the agent deletes the heartbeat when done. Always set `--expires-in` or `--max-runs`. Heartbeats cannot be edited beyond their cadence; delete and recreate to change the task.

For a fresh agent on each run, use `paseo schedule create` instead.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Handoff, committee, or advisor briefing | `references/workflows.md` | Transferring a task, convening two analysts, or requesting a second opinion |
