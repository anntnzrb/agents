# Loop extension

Purpose: `/loop` runs follow-up iterations until a breakout condition is satisfied.

## File map
- `index.ts`: tool registration, loop state, selector UI, compaction integration

## Navigation
Start at `index.ts`.

## Stop Rules
- Preserve existing breakout and user-interrupt behavior.
- Do not add autonomous side effects outside the follow-up iteration loop.
