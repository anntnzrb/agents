# Spawn Pi extension

## Purpose
Minimal pi-only subagent fanout.
Spawn one or more child `pi` processes.
Inherit current model + thinking.
Always start fresh.

## Files
- `index.ts` — tool registration, param validation, orchestration
- `cli.ts` — child pi argv construction + parent CLI inheritance
- `runner.ts` — child process execution, JSON event parsing, recursion guard
- `results.ts` — output aggregation, truncation, progress text, TUI rendering
- `types.ts` — shared result/type definitions
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Pi-only. No Codex/Claude/Gemini spawning.
- Inherits current model + thinking.
- Always runs child pi with `--no-session`.
- Hard-disables `spawn_pi` inside child processes by refusing to register the tool whenever `PI_SPAWN_DEPTH > 0`.
- Forwards built-in tools restriction and extension flags from parent CLI.
- Hard-codes one spawn level only.
- Child prompt contract stays minimal but explicit: task, concise final answer only, no further delegation.

## Navigation
Start at `index.ts`, then `runner.ts`, then `results.ts`.
If child argv/inheritance looks wrong, inspect `cli.ts`.
