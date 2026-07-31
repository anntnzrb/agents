---
name: session-finder
description: Locate saved OMP, Pi, Codex, T3 Code, and OpenCode conversations by remembered content or cwd.
---

# Session Finder

Use the bundled CLI to search saved sessions across all supported harnesses:

```bash
uv run --script <skill-dir>/scripts/cli.py QUERY [--limit N] [--harness HARNESS]... [--root HARNESS=PATH]...
```

- `QUERY`: One or more arguments. Quoted arguments are still split on whitespace; they are not phrase searches.
- `--limit N`: Limit results after ranking.
- `--harness {omp,pi,codex,t3code,opencode}`: Repeat to select harnesses. Omit to search all five.
- `--root HARNESS=PATH`: Repeat to replace that harness's defaults. Qualify every root with its harness.

Query terms use case-insensitive substring matching with AND semantics. Every term MUST occur within one searchable
category: title, aggregated user messages, aggregated transcript text, or cwd.

The CLI writes exactly one compact JSON array to stdout. Every record has exactly these 12 fields:

`harness`, `session_id`, `title`, `cwd`, `timestamp`, `updated_at`, `archived`, `storage_path`, `resume_argv`,
`match_type`, `score`, `snippet`.

`resume_argv` is an argv array or `null`; timestamps are millisecond UTC strings. Results are ranked by strongest
match, then recency, then deterministic identity fields.

| Harness | Default store(s) | `--root` meaning | Archived search | `resume_argv` |
| --- | --- | --- | --- | --- |
| OMP | `${XDG_DATA_HOME}/omp/sessions`, `~/.omp/agent/sessions`, and `<PI_CODING_AGENT_DIR>/sessions`; sibling `archive/sessions` | Session tree | Yes; `.jsonl.gz` cold archives | Active: `["omp","--resume",<absolute-jsonl>]`; cold archive: `null` |
| Pi | `PI_CODING_AGENT_SESSION_DIR`; merged global/project `sessionDir`; otherwise `<PI_CODING_AGENT_DIR or ~/.pi/agent>/sessions` | Session tree | Files found in the selected tree | `["pi","--session",<absolute-jsonl>]` |
| Codex | `<CODEX_HOME or ~/.codex>/sessions` and `archived_sessions` | Codex home | Yes | `["codex","resume",<session-id>]` |
| T3 Code | `<T3CODE_HOME or ~/.t3>/{userdata,dev}/state.sqlite` | Database file | Yes; deleted threads excluded | `null` |
| OpenCode | `OPENCODE_DB`, or `opencode.db` and `opencode-*.db` under `${XDG_DATA_HOME:-~/.local/share}/opencode` | Database file | Yes | `["opencode",<cwd>,"--session",<session-id>]`, omitting `<cwd>` when empty |

1. Run a broad query without `--harness` to search all five stores.
2. For `[]`, broaden or replace whitespace terms, then rerun.
3. For noisy results, tighten terms or add repeatable `--harness` filters, then rerun.
4. Report ranked candidates with harness, title, cwd, timestamp, session ID, archive state, and storage path.
5. Wait for the user to explicitly choose a candidate before resuming it.
6. Execute a non-null `resume_argv` only as the provided argv array.
7. For `resume_argv: null`, report the harness, session ID, and storage path.

NEVER reconstruct, display, or execute a shell-formatted resume command.
