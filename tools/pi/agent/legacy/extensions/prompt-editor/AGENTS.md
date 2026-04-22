# Prompt editor extension

Purpose: custom prompt editor with named modes, prompt history, and model/thinking presets.

## File map
- `index.ts`: extension wiring
- `modes-state.ts`: shared mode types, constants, runtime state
- `modes-core.ts`: mode storage, inference, persistence, apply logic
- `modes-ui.ts`: `/mode` flows, selectors, edit/configure UI
- `editor.ts`: custom editor and prompt history loading

## Navigation
Start at `index.ts`, then `modes-core.ts`, `modes-ui.ts`, and `editor.ts`.
