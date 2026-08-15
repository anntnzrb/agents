# LLM Patcher extension

## Purpose

Minimal provider-payload patcher.
Adjust model behavior at the provider request boundary.
OpenAI GPT-5 Responses payloads only for now.
Patch trace logging is an invariant.

## Files

- `index.ts` — loads config, registers `before_provider_request`, runs payload patchers, appends trace logs
- `config.ts` — loads minimal JSONC config with defaults and trace log path
- `llm-patcher.jsonc` — extension-local JSONC settings file, synced with this legacy extension
- `openai.ts` — OpenAI Responses payload detection + GPT-5 verbosity patch + trace reasons
- `types.ts` — shared narrow helpers + patch/trace types
- `package.json` — marks this legacy extension package as ESM for local typechecking
- `tsconfig.json` — strict TS config matching sibling extensions

## Invariants

- Prefer pure patchers.
- Return fresh payloads; no in-place mutation.
- Every provider request appends a JSONL trace entry with rule, model, changed flag, reason, and field changes.

## Current Scope

- Set `text.verbosity` from config for GPT-5 OpenAI-style Responses payloads.

## Stop Rules

- Do not broaden provider/model coverage unless explicitly requested.
- Keep trace logging intact while refactoring patch rules.
