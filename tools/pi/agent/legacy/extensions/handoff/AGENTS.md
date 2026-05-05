# Handoff Extension

## Purpose
Create a clean follow-up session from the current conversation by generating a focused handoff prompt for a new thread.

## Files
- `index.ts` — registers `/handoff`, collects conversation context, generates/edit handoff prompt, creates the new session
- `tsconfig.json` — strict TS config matching sibling extensions

## Invariants
- Interactive UI only
- Human-in-the-loop: generated handoff prompt is editable before creating the new session
- Uses parent session tracking when creating the new session
- Meant for session hygiene, not delegation

## Stop Rules
- Do not turn handoff into task delegation or background execution.
- Preserve the editable review step before creating a new session.
