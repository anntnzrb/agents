---
name: herdr
description: Use Herdr to control terminal panes, tabs, workspaces, commands, agents, and sessions only when explicitly requested.
---

# Herdr

Herdr organizes terminals into workspaces, tabs, and panes; recognizes coding agents in panes; exposes the current session through `herdr` CLI.

## Preconditions

Before any control command, verify this agent runs in a Herdr-managed pane:

```bash
test "${HERDR_ENV:-}" = 1
```

If the check fails, say that you are not running inside Herdr and stop; NEVER inspect or control the focused Herdr session from outside Herdr. If it passes, `herdr` in `PATH` targets the current session and can inspect neighboring work, create terminal layout, start agents/commands, read output, and wait for state changes.

## CLI discovery

Installed binary = syntax authority. Start:

```bash
herdr --help
```

Print a command group by running it without a subcommand:

```bash
herdr agent
herdr pane
herdr workspace
herdr tab
herdr worktree
herdr terminal
herdr notification
herdr integration
herdr session
```

NEVER run bare `herdr` for discovery: it launches or attaches the TUI. NEVER omit arguments from a mutating nested command: e.g. `herdr workspace create` executes with defaults. Most control commands return JSON; read IDs/state from responses, NEVER predict them.

## Layout, panes, agents

- Workspace/tab/pane: terminal topology.
- Pane commands: raw terminals, shells, tests, servers, input, output.
- Agent commands: recognized coding agent occupying a pane; validate identity and interpret `idle`, `working`, `blocked`, `done`, `unknown`.

Pane exists without an agent. `agent start` requires an existing available shell pane and NEVER creates, splits, or moves layout. Agent commands accept a unique live agent name or the pane ID currently hosting that agent, NEVER terminal IDs or bare agent-kind labels. Names: `[a-z][a-z0-9_-]{0,31}`, unique among live agents; name follows the current pane occupant and clears when that agent exits, is released, or is replaced.

States: `idle` = agent ready for input and tab seen in focused Herdr UI; `done` = same underlying idle state after unseen background work finishes; focusing the tab or targeting the pane or agent with a focus command marks it seen, but CLI reads do not; `blocked` = recognized approval/question UI; `unknown` = agent present but classification uncertain, not proof of completion.

## IDs and caller context

Public IDs are opaque stable handles:

- workspace: `w1`
- tab: `w1:t1`
- pane: `w1:p1`

Closed tab/pane IDs are never reused. Moving a pane to another workspace gives it a new workspace-qualified pane ID. After `pane move`, use `.result.move_result.pane.pane_id` or the live agent name; `.result.move_result.previous_pane_id` is the old ID, which only the moved process's inherited caller context continues to resolve and which is not a general agent target.

Managed panes receive caller context:

```bash
printf '%s\n' "$HERDR_WORKSPACE_ID" "$HERDR_TAB_ID" "$HERDR_PANE_ID"
```

Prefer `--current` when a pane command should target the calling pane. An omitted target may select the UI-focused pane belonging to another user/client.

Discover live state:

```bash
herdr workspace list
herdr tab list --workspace "$HERDR_WORKSPACE_ID"
herdr pane current --current
herdr pane list --workspace "$HERDR_WORKSPACE_ID"
herdr agent list
```

Creation responses expose IDs for subsequent use: `workspace create` → `.result.workspace`, `.result.tab`, `.result.root_pane`; `tab create` → `.result.tab`, `.result.root_pane`; `pane split` → `.result.pane`.

## Start and coordinate agents

Default to a sibling pane in the current tab and current working directory. Do not create a workspace, tab, worktree, or different cwd unless the user explicitly requests that topology or location. Honor a direction requested by the user; otherwise inspect the caller:

```bash
herdr pane layout --pane "$HERDR_PANE_ID"
```

Split a wide pane → right and a narrow or tall pane → down; avoid repeated same-direction splits that make columns unusably narrow or rows too short. Keep the user's focus in the calling pane and explicitly preserve the caller's working directory:

```bash
herdr pane split --current --direction right --cwd "$PWD" --no-focus
```

Use `down` when appropriate. Read the new ID from `.result.pane.pane_id`.

Available shell pane = interactive prompt, shell itself foreground, no foreground command/editor/agent. Start a supported agent with a useful unique name:

```bash
herdr agent start reviewer --kind codex --pane <returned-pane-id>
```

Use the kind requested by the user; run `herdr agent` for installed kinds/options. Pass native agent arguments only after `--`:

```bash
herdr agent start reviewer --kind codex --pane <returned-pane-id> -- <agent-args...>
```

`agent start` returns only after detecting the expected agent in the same pane and considering it ready for interactive input; default startup timeout: 30 seconds.

Submit through the agent surface:

```bash
herdr agent prompt reviewer "Review the current diff and report only actionable findings." --wait --timeout 120000
```

`agent prompt` atomically sends text plus encoded Enter and honors live bracketed-paste mode. For normal agent work, `--wait` waits for the first settled `idle`/`done`/`blocked` state; do not repeat these defaults with `--until`. A prompt sent from a non-working state must produce an observed lifecycle change within five seconds, else returns `agent_prompt_stalled`; this tracks lifecycle state, not an individual turn, so active-turn completion may satisfy it.

Use `--until` only for a state-specific workflow, such as waiting for an already-running agent to request input:

```bash
herdr agent wait reviewer --until blocked --timeout 120000
```

Without `--until`, standalone `agent wait` has the same settled-state defaults as `agent prompt --wait`.

Use logical keys:

```bash
herdr agent send-keys reviewer esc
herdr agent send-keys reviewer ctrl+c
```

Herdr validates every key before writing bytes. Read via the resolved agent:

```bash
herdr agent get reviewer
herdr agent read reviewer --source recent-unwrapped --lines 120
```

If a wait fails or returns `blocked`, inspect `agent get` and `agent read` before deciding what input to send. Use the pane surface only when raw terminal control is intentional.

## Ordinary commands

Create a sibling pane with the same geometry rule, preserve the caller's working directory, and keep user focus unchanged:

```bash
herdr pane split --current --direction right --cwd "$PWD" --no-focus
```

Read the returned `.result.pane.pane_id`, then:

```bash
herdr pane run <returned-pane-id> "just test"
herdr pane wait-output <returned-pane-id> --match "test result" --timeout 120000
herdr pane read <returned-pane-id> --source recent-unwrapped --lines 120
```

`pane run` atomically sends command text plus Enter. `pane wait-output` searches the selected snapshot immediately, so existing output can match. `--match <text>` = literal substring; `--regex <pattern>` = Rust regex. Omitted `--timeout` = indefinite wait.

Read sources:

- `visible`: currently rendered viewport.
- `recent`: recent rendered output, including soft wraps.
- `recent-unwrapped`: recent output with soft wraps joined; prefer it for logs/transcripts.
- `detection`: plain-text bottom-buffer snapshot used for agent detection.

Use `--format ansi` when colors and terminal styling are evidence; otherwise text.

`--lines` requests more rows from the pane's available screen and host scrollback. If increasing it does not reveal more of a completed response, the pane is probably running the agent on the terminal's alternate screen. Rows leaving the alternate screen do not enter Herdr's host scrollback, so a larger line count cannot recover them. After that failed read, as a fallback only, ask the agent to write its complete response as Markdown in a temporary directory and reply only with the file path, then read the file directly. NEVER request file output in the initial prompt.

## Safety

- Use `--no-focus` for background work unless the user asked to switch context.
- Use `--current`, an explicit pane ID, or a unique agent name. NEVER rely on another client's focused pane.
- Parse IDs from JSON responses. NEVER derive them from sidebar order or examples.
- NEVER close workspaces, tabs, panes, or sessions you did not create unless the user explicitly asked.
- NEVER run `herdr server stop` from an active session unless the user explicitly intends to stop the server and its pane processes.
- NEVER kill the main Herdr process. Use named test sessions for experiments that need an isolated server.
- CLI server errors are JSON on stderr with exit status 1. CLI syntax errors exit with status 2.
