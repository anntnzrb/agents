# shard extension

## Purpose
Minimal Pi-only child delegation primitive.
Launch disposable child `pi` processes for bounded work and report results back to the parent.
The parent session remains the orchestrator.

## Tool contract
- Input uses only `tasks: string[]`; a single task is `tasks: ["..."]`.
- `tasks[]` is an independent batch. Every task in one call may run concurrently.
- Dependent phases must be split into multiple parent-orchestrated `shard` calls.
- Omitted mode derives from task count:
  - one task -> `worker`
  - multiple tasks -> `explorer`
- `worker` is parent-like and accepts exactly one task.
- `explorer` is strict read-only fanout: active tools are filtered to `read`, `grep`, `find`; no shell or mutation tools.
- `timeoutSec`, `maxTurns`, and `maxToolCalls` are optional and have no defaults.
- `maxTurns` and `maxToolCalls` are strict budget kill switches; use only for explicit bounded runs.
- Child prompts require structured reports so parent output is predictable and compact.
- Active child process groups are killed on abort/timeout/budget termination and on `session_shutdown`.
- Children run through an inline watchdog process; if the invoking parent Pi process dies, the watchdog kills the child process group/process tree.
- Child stdout/stderr have post-exit guards, and a child that emits a final response but fails to exit is terminated.

## Files
- `index.ts` — tool registration, param validation, orchestration
- `planning.ts` — pure task/mode/timeout/tool-selection helpers
- `cli.ts` — child Pi argv + parent CLI inheritance + child prompts
- `runner.ts` — child process execution, JSON event parsing, timeout/abort cleanup, recursion guard
- `results.ts` — output aggregation, truncation, progress text, TUI rendering
- `types.ts` — result/type definitions
- `*.test.ts` — targeted unit tests
- `tsconfig.json` — strict TS config

## Notes
- Pi-only. No Codex/Claude/Gemini child launching.
- Child Pi runs with `--no-session`.
- Disable `shard` in child when `PI_SHARD_DEPTH > 0`.
- Worker mode inherits parent runtime active tools via `pi.getActiveTools()`.
- Explorer mode keeps parent extension flags but filters callable tools.
- Forward built-in tool restrictions + extension flags from parent CLI.
- Hard-code one child-delegation level.
- JSON mode is machine truth; no tmux/PTY/job runtime here.

## Navigation
Start `index.ts` -> `planning.ts` -> `runner.ts` -> `results.ts`.
If child argv/inheritance is wrong, inspect `cli.ts`.
