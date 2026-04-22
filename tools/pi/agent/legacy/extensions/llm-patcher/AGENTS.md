# LLM Patcher extension

## Purpose
Minimal provider-payload patcher.
Adjust model behavior at the provider request boundary.
OpenAI GPT-5 Responses payloads only for now.
Mandatory patch trace logging included.

## Files
- `index.ts` — loads config, registers `before_provider_request`, runs payload patchers, appends trace logs
- `config.ts` — loads minimal JSONC config with defaults and trace log path
- `../../llm-patcher.jsonc` — synced user-level settings file (`~/.pi/agent/llm-patcher.jsonc`)
- `openai.ts` — OpenAI Responses payload detection + GPT-5 verbosity patch + trace reasons
- `types.ts` — shared narrow helpers + patch/trace types
- `tsconfig.json` — strict TS config matching sibling extensions

## Notes
- Pure patchers preferred.
- Return fresh payloads; no in-place mutation.
- Current behavior: set `text.verbosity` from config for GPT-5 OpenAI-style Responses payloads.
- Every provider request appends a JSONL trace entry with rule, model, changed flag, reason, and field changes.
