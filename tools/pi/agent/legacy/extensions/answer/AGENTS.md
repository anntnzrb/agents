# Answer extension

Purpose: /answer extracts questions from last assistant message, shows Q&A TUI, sends answers as a user turn.

## File map
- index.ts: command wiring, guard checks, orchestration
- constants.ts: prompts + defaults
- types.ts: shared types
- assistant-text.ts: find last assistant message text
- extraction.ts: model call + JSON parse + loader UI
- qna-component.ts: interactive TUI component

## Navigation
Start at index.ts. For extraction flow see extraction.ts; for UI behavior see qna-component.ts.
