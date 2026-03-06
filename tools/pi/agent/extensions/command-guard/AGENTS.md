# Command guard extension

Purpose: generic, policy-driven guard for agent `bash` tool calls.

## File map
- `index.ts`: pi entrypoint; wires config path into the extension factory
- `command-guard.jsonc`: policy file for blocked commands and messages
- `extension.ts`: event hook; loads config and blocks matching tool calls
- `config.ts`: JSONC parsing and config validation; fail-closed on invalid config
- `matcher.ts`: rule evaluation against inspected commands/executables
- `shell.ts`: shell segmentation and tokenization helpers
- `wrappers.ts`: wrapper unrolling for `env`, `sudo`, shells with `-c`, and similar commands
- `types.ts`: shared config and result types
- `command-guard.test.ts`: regression tests for config loading and matching behavior

## Navigation
Start at `index.ts`, then `extension.ts`, then `config.ts` and `matcher.ts`.
If matcher behavior is wrong, inspect `shell.ts` and `wrappers.ts` next.
