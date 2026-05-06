# Provider patcher extension

Purpose: inject small provider-native request patches into payloads and expose a single `/tier` chooser for request service tier options that apply to the currently selected model.

## File map
- `index.ts`: command/event wiring and status updates
- `settings.ts`: native `settings.json` namespace load/save
- `logic.ts`: generic patch parsing and payload mutation helpers
- `patchers.ts`: provider patch registry/orchestration and current-model option discovery
- `openai.ts`: OpenAI Responses/Codex payload detection + service-tier patching
- `index.test.ts`: helper tests for tier parsing and payload mutation

## Navigation
Start at `index.ts`.

## Stop Rules
- Keep provider matching generic: prefer API/payload shape over hardcoded model IDs.
- Do not inject provider options into unsupported provider payloads.
- Add new providers as dedicated modules plus registry entries; do not sprawl provider-specific logic into `index.ts`.
