# Clarify Extension

## Purpose
Interactive-only `clarify` tool for 1..3 focused user questions when the model is blocked on requirements, preferences, or approvals.
Supports recommended/default options, optional timeout auto-select, waiting notification, and richer progress/navigation UI.

## Files
- `index.ts` — thin tool registration + prompt metadata + execute wiring
- `models.ts` — schemas and typed result models
- `results.ts` — pure normalization/validation/result helpers
- `ui.ts` — custom TUI flow for single-question and multi-question review flow
- `tsconfig.json` — strict TS config matching sibling minimal extensions

## Invariants
- No slash commands
- Non-interactive mode fails cleanly
- Single question: simple flow
- Multi-question: tabbed flow + review/submit

## Stop Rules
- Ask only focused questions that unblock requirements, preferences, or approvals.
- Keep this extension interactive-only; do not add non-interactive fallback behavior unless explicitly requested.
