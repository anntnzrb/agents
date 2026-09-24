---
disable-model-invocation: true
name: autommit
description: "Use when the user asks for autommit, unattended commits, atomic commit splitting, or recovery."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Autommit

Create the smallest honest set of commits from the current repository changes. One command owns the loop: it prepares the staged snapshot, asks a model for a plan, validates that plan against the same snapshot, gates broad plans through an independent atomicity critic, and creates the commits with compare-and-swap. The model plans. The CLI owns every mutation and every safety check.

An explicit request to `autommit`, automatically commit, or run the unattended atomic commit workflow authorizes local commit creation. It never authorizes push, force, reset, clean, stash, amend, or unrelated history edits.

## Public entrypoint

```text
uv run --script <skill-dir>/scripts/cli.py [options] [context ...]
```

| Option | Meaning |
|---|---|
| `--repo PATH` | Target repository (default: current directory) |
| `--scope auto\|staged\|all` | `auto` reuses an existing staged snapshot and stages everything only when nothing is staged; `staged` requires an existing snapshot and never stages; `all` always stages everything (default: `auto`) |
| `--model`, `--base-url`, `--api-key`, `--timeout`, `--reasoning-effort` | Endpoint overrides that beat environment variables and the built-in defaults |
| `--base REV` | Rewrite mode only: rebuild the commits since this ancestor revision |
| `--smoke CMD` | Run one validation command in the temporary worktree after each commit (default: off) |
| `--dry-run` | Print the inventory and snapshot, call no model, create nothing |
| `--json` | Emit one `autommit/v1` object on stdout; exit codes are unchanged |

Positional arguments and repeated `--context` values pass user intent to the planner unchanged.

Other subcommands: `cli.py models [--filter TEXT]` lists the model ids the configured endpoint advertises, so a model can be chosen before a run. `cli.py rewrite --base <rev>` is described under Modes. `run` stays the default when no subcommand is given.

Environment variables: `AUTOMMIT_MODEL`, `AUTOMMIT_BASE_URL`, `AUTOMMIT_API_KEY`, `AUTOMMIT_TIMEOUT`, `AUTOMMIT_REASONING_EFFORT`, plus the `OPENAI_*` aliases.

Precedence: CLI flags, then environment variables, then the owner defaults in `lib/autommit/config.py` (`DEFAULT_MODEL`, `DEFAULT_BASE_URL`, `DEFAULT_API_KEY`, `DEFAULT_REASONING_EFFORT`, `DEFAULT_TIMEOUT`). With the defaults set, a bare `cli.py` run needs no flag or variable. Change a default in that file in the SSOT. Autommit reads no configuration file and creates none.

`keyless` is the conventional value for a gateway that accepts any key. Against an endpoint that requires a real key it produces `provider_error` with HTTP 401 or 403, not `missing_api_key`.

## Modes

| Mode | Command | Use it when |
| --- | --- | --- |
| Run | `cli.py [options]` | The staged snapshot is what should become commits |
| Rewrite | `cli.py rewrite --base <rev> [options]` | Committed and uncommitted changes since a revision must become logical commits again |

Rewrite freezes the current worktree, including uncommitted work, into a target tree, rebuilds the commits from `--base` inside a detached temporary worktree, and moves the branch only after the rebuilt tree equals that frozen tree. It never pushes, and the previous tip stays reachable through the reflog.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| CLI contract, plan shape, exit codes, recovery | `references/protocol.md` | Before every run or recovery |
| Planner and critic contracts | `references/prompts.md` | Before changing plan rules or critique behavior |
| Rules, valves, message and inference policy | `references/philosophy.md` | Before changing limits, prompts, or critic behavior |

## Workflow

1. Read the required references the table names for the change.
2. Run the public entrypoint from the target repository. Prefer the default `--scope auto`.
3. Report the command output verbatim: created commits oldest to newest, or the exact structured error with its recovery point.
4. On failure, report the error code and the `operation.lock` or `recovery.json` path when the command names one. Do not repair state by hand.

## Invariants

- Never bypass `validate-plan`, critic gating, snapshot binding, the operation lock, receipt recovery, the temporary worktree, tree equality, or compare-and-swap creation.
- Never remove a stale lock automatically. Preserve evidence and state on every refusal or failure.
- Never replace this loop with direct `git add`, `git commit`, or `git update-ref` commands.
- Never push unless the user explicitly asks for it.

<critical>
The model plans; the CLI owns all mutation. A created tree must exactly equal the prepared index tree, or nothing is created.
</critical>
