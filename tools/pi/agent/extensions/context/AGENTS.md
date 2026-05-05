# Context extension

Purpose: `/context` shows loaded extensions, skills, project context files, and session/context usage.

## File map
- `index.ts`: command wiring, skill tracking, data gathering, TUI view

## Navigation
Start at `index.ts`.

## Stop Rules
- Keep this extension read-only and UI/reporting scoped.
- Do not change loaded context, tools, skills, or session usage from this extension.
