---
name: paseo
description: "Use when delegating to Paseo subagents, handing off tasks, getting second opinions, or setting Paseo heartbeats."
license: AGPL-3.0-or-later
---

# Paseo

Paseo is a daemon that runs coding agents in workspaces. Agents it launches can launch and steer other agents. Drive it through the injected Paseo tools when they are available, otherwise through the `paseo` CLI. Pi agents receive no injected tools; use the CLI.

Paseo sets `PASEO_AGENT_ID` in every agent it launches. An agent you create from that session becomes your subagent. On your own host, omit the workspace to share your files.

## Connected hosts

Call `list_hosts` to discover the calling daemon and registered destinations. Use a destination's `serverId`, not its display label, with `create_workspace`, `list_workspaces`, `create_agent`, `send_agent_prompt`, `get_agent_status`, `get_agent_activity`, or `list_agents`. Omit `serverId` for the calling daemon; other injected tools operate there.

Keep each agent's `serverId` and `agentId` together. For a remote agent, first list or create a workspace on that host, then pass its `workspaceId` and `serverId` to `create_agent`. Paths and workspace IDs belong to the destination. Remote `list_agents` does not default to the caller's directory; pass `cwd` to filter it.

Manage host registrations with `paseo host`; use the returned `registrationId` for updates and removal. Select the calling daemon with `--host <address>` when needed.

## Workspaces

For `create_workspace`, use `path` for a local directory or source checkout and `projectId` for the owning project. A worktree can resolve its source from `projectId` when `path` is omitted. Worktree checkout modes are `branch-off`, `checkout-branch`, and `checkout-pr`.

Background workspaces remain durable but are hidden from default lists and the sidebar. When `background` is omitted, the new workspace inherits the calling workspace's value. Without a caller, the value defaults to `false`. Override it only at the user's request. Set `includeBackground: true` in `list_workspaces` or `list_agents` to include them.

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
- Agent-scoped `send_agent_prompt` and `paseo send` default to `steer`; top-level sends default to `interrupt`. Override with `activeTurnBehavior` or CLI `--behavior steer|interrupt`. Steering falls back to interruption when unavailable. Agent-scoped sends return a queued receipt; top-level sends return after dispatch acknowledgement.

## Waiting

- Agents routinely take 10 to 30 minutes. Injected tools notify you on completion, errors, or permission requests, including across hosts. Do not poll `list_agents` or `get_agent_status`. When an explicit reply is needed instead of a callback, ask the sender to check `list_hosts` for the recipient's server before setting `notifyOnFinish: false`.
- From the CLI, block with `paseo agent wait` only when your next step needs the result; otherwise keep working.

## Heartbeats

A heartbeat re-prompts the same agent on a cron cadence and keeps its conversation. Use one for unattended goals: state the next small step, the checks to run each time, and that the agent deletes the heartbeat when done. Always set `--expires-in` or `--max-runs`. Heartbeats cannot be edited beyond their cadence; delete and recreate to change the task.

For a fresh agent on each run, use `paseo schedule create` instead.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Handoff, committee, or advisor briefing | `references/workflows.md` | Transferring a task, convening two analysts, or requesting a second opinion |
