# Guardrails extension

Purpose: generic, policy-driven guardrails for agent tool calls.

## File map

- `index.ts`: pi entrypoint; loads config and blocks matching tool calls
- `guardrails.jsonc`: policy file for shell-command rules and protected paths
- `config.ts`: JSONC parsing and config validation; invalid config fails closed with diagnosable errors
- `hints.ts`: agent-facing replacement hints for warnings; derives live tool signatures from `pi.getAllTools()` with static fallback
- `matcher.ts`: shell rule evaluation against inspected commands/executables
- `paths.ts`: protected-path matching for read/write/edit
- `shell.ts`: shell segmentation and tokenization helpers
- `wrappers.ts`: wrapper unrolling for `env`, `sudo`, shells with `-c`, and similar commands
- `types.ts`: shared config and result types
- `guardrails.test.ts`: regression tests for config loading and matching behavior

## Navigation

Start at `index.ts`, then `config.ts`, `matcher.ts`, and `paths.ts`.
If shell matching is wrong, inspect `shell.ts` and `wrappers.ts` next.

## Invariants

- Invalid guardrail config blocks risky execution rather than silently allowing it.
- Warning hints must match live tool signatures when available.

## Stop Rules

- Do not relax policy matching while modernizing prompts or docs.
- Keep config changes separate from matcher behavior unless the task explicitly couples them.
