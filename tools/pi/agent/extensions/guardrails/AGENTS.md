# Guardrails extension

Purpose: generic, policy-driven guardrails for agent `bash` tool calls.

## File map
- `index.ts`: pi entrypoint; loads config and blocks matching tool calls
- `guardrails.jsonc`: policy file for blocked commands and messages
- `config.ts`: JSONC parsing and config validation; fail-closed on invalid config
- `matcher.ts`: rule evaluation against inspected commands/executables
- `shell.ts`: shell segmentation and tokenization helpers
- `wrappers.ts`: wrapper unrolling for `env`, `sudo`, shells with `-c`, and similar commands
- `types.ts`: shared config and result types
- `guardrails.test.ts`: regression tests for config loading and matching behavior

## Navigation
Start at `index.ts`, then `config.ts` and `matcher.ts`.
If matcher behavior is wrong, inspect `shell.ts` and `wrappers.ts` next.
