# Pi Goal Extension

## Purpose

Persistent Codex-style thread goals for Pi:

- `/goal <objective>` starts or replaces a long-running objective
- `/goal status|pause|resume|clear|suggest` controls lifecycle and suggestion
- continuation messages keep the active goal in model context until complete, paused, or cleared
- `update_goal` tool lets the model mark the goal complete after evidence-based audit

## Files

- `index.ts` — Pi entrypoint; wires command, tools, renderers, lifecycle events, footer contribution
- `state.ts` — goal state, session restore, accounting, tool activation
- `prompts.ts` — Codex-derived continuation prompt with strict completion audit
- `format.ts` — status labels, elapsed formatting, summaries, objective truncation
- `command.ts` — `/goal` parser, handler, dynamic completions, suggestion prompts
- `tools.ts` — `update_goal` tool definition with compact custom rendering
- `render.ts` — compact two-line goal-event and tool-call renderer (grep-style)
- `footer.ts` — optional footer contribution registered through shared registry
- `footer.test.ts` — footer badge rendering and contribution registration tests
- `render.test.ts` — renderer output tests including elapsed omission and truncation
- `index.test.ts` — parser, formatting, state, prompt, lifecycle, and tool activation tests
- `tsconfig.json` — strict TS config matching sibling extensions

## Invariants

- `update_goal` only marks active goals `complete`.
- Pause, resume, and clear are user/runtime controlled — not model-accessible through tools.
- Active goal continuation prompt must include the objective and strict completion audit.
- Goal state is persisted with custom entries and restored from the active branch.
- Reload pauses active goals instead of silently resuming autonomous continuation.
- `update_goal` is exposed as a tool only while the goal is active.
- The footer badge is registered as an optional contribution; no extension-to-extension hard dependency.

## Stop Rules

- Keep behavior close to Codex native `/goal` unless explicitly asked otherwise.
- Do not weaken completion-audit language.
- Do not let the model pause/resume/clear goals through `update_goal`.
