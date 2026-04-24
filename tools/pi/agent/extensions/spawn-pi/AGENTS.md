# Spawn Pi extension

## Purpose
Minimal pi-only subagent fanout.
Spawn child `pi` processes for one or more independent tasks.
Inherit current model + thinking. Always fresh session.

## Files
- `index.ts` — tool registration, param validation, orchestration
- `cli.ts` — child pi argv + parent CLI inheritance
- `runner.ts` — child process execution, JSON event parsing, recursion guard
- `results.ts` — output aggregation, truncation, progress text, TUI rendering
- `types.ts` — result/type definitions
- `tsconfig.json` — strict TS config

## Notes
- Pi-only. No Codex/Claude/Gemini spawning.
- Child pi runs with `--no-session`.
- Disable `spawn_pi` in child when `PI_SPAWN_DEPTH > 0`.
- Inherit parent runtime active tools via `pi.getActiveTools()`.
- Forward built-in tool restrictions + extension flags from parent CLI.
- Hard-code one spawn level.
- Child prompt contract: task, concise final answer only, no further delegation.

## Navigation
Start `index.ts` -> `runner.ts` -> `results.ts`.
If child argv/inheritance wrong, inspect `cli.ts`.
