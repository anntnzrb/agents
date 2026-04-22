# Todos extension

Purpose: file-backed todo manager with a tool and /todos TUI.

## File map
- index.ts: registration + GC on session start
- tool.ts: todo tool implementation
- command.ts: /todos TUI command
- components.ts: TUI components
- storage/: file I/O, locks, settings
- utils.ts: ids, status, filtering
- render.ts: rendering helpers
- serialize.ts: tool serialization
- constants.ts: constants
- types.ts: shared types/schema

## Navigation
Start at index.ts, then tool.ts or command.ts.
