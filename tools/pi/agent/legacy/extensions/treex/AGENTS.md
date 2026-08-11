# Treex Extension

## Purpose

`/treex` is an experimental tree navigation/rewrite command intended to eventually extend or replace native `/tree` workflows.

It starts from native tree-selection UX, then for ancestor targets offers interactive-rebase-style context cleanup:

- pick entries verbatim
- summarize with detailed context-preserving compression
- drop noisy history
- create a synthetic cleaned branch

## Files

- `index.ts` — command orchestration, native navigation fallback, rewrite application
- `tree-selector.ts` — wrapper around native Pi `TreeSelectorComponent`
- `action-list.ts` — minimal interactive P/S/D action editor (group actions, no debug/export path)
- `summarize.ts` — compact summary prompt assembly, model call, rewrite assembly
- `tree-utils.ts` — pure tree/path/action helpers

## Invariants

- Native `/tree` must remain untouched until explicitly replaced.
- Prefer native `ctx.navigateTree()` for plain navigation and non-ancestor targets.
- Use native Pi tree selector directly; do not vendor selector internals.
- Keep private Pi internals isolated in `index.ts` until public append-summary APIs exist.
- Current intentional hack: branch-summary writes use private `sessionManager._appendEntry(...)` because public `appendBranchSummary(...)` is not available in the current Pi runtime surface.
- If/when public append-summary API lands, replace `_appendEntry` first; fallback option without upstream changes is `appendCustomMessageEntry` summaries (with different native `/tree` semantics).
- Synthetic summaries must preserve source IDs and include file-operation metadata when derivable from tool calls or prior summary details.

## Stop Rules

- Do not intercept typed `/tree`.
- Do not add sync subprocess calls in UI/model paths.
- If changing command behavior, run typecheck and scenario-specific child Pi validation when practical.
