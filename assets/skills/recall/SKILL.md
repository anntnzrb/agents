---
name: recall
description: "Rebuild recent work context from session search and live git/gh state; for 'recall my work on X', 'catch me up'."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Recall

Before starting or resuming work, rebuild the user's recent working context and hand back a tight capsule of where things stand now and what to do next. Use for "recall my work on X", "catch me up", "what have I been working on", or "where did I leave off".

Two records hold the context. Session history holds what was done and decided. Live state (git branches, PRs, issues) holds what is true now. Search the first, verify against the second.

## Search backend

The bundled CLI searches saved sessions across harnesses:

```text
uv run --script <skill-dir>/scripts/cli.py QUERY [--limit N] [--harness HARNESS]... [--root HARNESS=PATH]...
```

- `QUERY`: whitespace-split terms; every term must occur within one searchable category (title, user messages, transcript text, or cwd); AND semantics, case-insensitive
- `--harness {omp,pi,codex,t3code,opencode}`: repeat to select; omit for all five
- Output: one compact JSON array; records carry `harness`, `session_id`, `title`, `cwd`, `timestamp`, `archived`, `storage_path`, `resume_argv`, `match_type`, `score`, `snippet`

| Harness | Default store | Archived search | `resume_argv` |
| --- | --- | --- | --- |
| OMP | `${XDG_DATA_HOME}/omp/sessions`, `~/.omp/agent/sessions`, `<PI_CODING_AGENT_DIR>/sessions`; sibling `archive/sessions` | Yes | Active: `["omp","--resume",<absolute-jsonl>]`; cold: `null` |
| Pi | `PI_CODING_AGENT_SESSION_DIR`; merged global/project `sessionDir`; else `<PI_CODING_AGENT_DIR or ~/.pi/agent>/sessions` | Yes | `["pi","--session",<absolute-jsonl>]` |
| Codex | `<CODEX_HOME or ~/.codex>/sessions` and `archived_sessions` | Yes | `["codex","resume",<session-id>]` |
| T3 Code | `<T3CODE_HOME or ~/.t3>/{userdata,dev}/state.sqlite` | Yes | `null` |
| OpenCode | `OPENCODE_DB`, or `opencode.db`/`opencode-*.db` under `${XDG_DATA_HOME:-~/.local/share}/opencode` | Yes | `["opencode",<cwd>,"--session",<session-id>]` |

NEVER reconstruct, display, or execute a shell-formatted resume command. `resume_argv` executes only as the provided argv array, and only after the user picks a candidate.

## Workflow

1. **Classify.** A specific prior chat to resume is a different task. Recall loads working context across recent chats before acting. If the user already gave a full state capsule (paths, branch, change), use it and skip the mining.
2. **Lock scope.** Pin the window ("recent" defaults to the last 7 days), the topic if named, and the workspace (default the active one). State the scope back. Never quietly turn "all" into "recent N", and never search another project's sessions without being asked.
3. **Search sessions.** Run the CLI broad first (no `--harness`); for `[]`, broaden or replace whitespace terms. For noisy results, tighten terms or add `--harness` filters. For a large corpus, fan out parallel read-only subagents, each with a query slice, returning the same schema per chat: topic, the user's goal, decisions, open threads, struggles, artifacts (PRs, tickets, branches), each citing the session id. Keep raw transcripts in the subagents; the main thread gets findings only.
4. **Sweep the shared record** when the topic names a feature, file, subsystem, area, or bug. Run `git log` and `gh` (issues, PRs, search) over the named target; read repo-local docs if the target has any. Search terms come from the topic and the session findings. A source that is unavailable is a gap: say so. Skip this step only for pure activity recall ("what did I do this week").
5. **Verify against live state.** Transcripts and stale tickets are history. Check surfaced PRs, branches, and tickets with `git` and `gh` before putting them in the brief.
6. **Write the brief.** See the contract below. Group by thread. Stay on the named topic.

## Output contract

Lead with the capsule, then thread status, then problems, then the next move.

- **Capsule.** At most 5 bullets. What this work is and where it stands overall.
- **Threads.** One line each, prefixed with exactly one status tag: `[merged #N]`, `[open PR #N]`, `[in flight <branch>]`, `[verified, uncommitted]`, `[reverted #N]`, or `[planned, not started]`. A thread with no tag is not done yet, so tag it.
- **Problems.** At most 5, the recurring ones. Include symptoms users keep reporting and any fix that shipped and got reverted, so the next attempt starts where the last one failed.
- **Next move.** The single most useful next action, concrete.

An adjacent feature or ticket stays out unless it blocks this one. Cite session findings by session id and shared-record findings by source (PR #, issue id). Sanitize private context before any public output.

Reply with the brief, to this contract.

Adapted from pstack recall (MIT, Lauren Tan) and the bundled session-search CLI (GPL-3.0-or-later, anntnzrb).
