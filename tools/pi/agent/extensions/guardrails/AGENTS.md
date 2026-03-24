# Guardrails extension

Purpose: generic, policy-driven guardrails for agent tool calls.

## File map
- `index.ts`: pi entrypoint; loads config and blocks matching tool calls
- `guardrails.jsonc`: policy file for bash rules and protected paths
- `config.ts`: JSONC parsing and config validation; fail-closed on invalid config
- `matcher.ts`: bash rule evaluation against inspected commands/executables
- `paths.ts`: protected-path matching for read/write/edit
- `shell.ts`: shell segmentation and tokenization helpers
- `wrappers.ts`: wrapper unrolling for `env`, `sudo`, shells with `-c`, and similar commands
- `types.ts`: shared config and result types
- `guardrails.test.ts`: regression tests for config loading and matching behavior

## Navigation
Start at `index.ts`, then `config.ts`, `matcher.ts`, and `paths.ts`.
If bash matching is wrong, inspect `shell.ts` and `wrappers.ts` next.
