# smolui

smolui collapses noisy built-in tool cards in omp's interactive transcript. It changes only what the terminal draws: tool results sent to the model, headless modes (print, JSON, RPC, ACP), and native Tern views are untouched. Expanding a card (ctrl+o) always shows omp's stock rows.

## What each card keeps

| Tool | Collapsed card keeps | Hides |
| --- | --- | --- |
| `bash` | Command, `Wall · Timeout · Exit` facts, truncation and artifact warnings | Output rows |
| `eval` (success) | Cell titles, output, `display()` views | Code pane |
| `eval` (error) | Cell titles, traceback | Code pane, output of passing cells |
| `edit`, `apply_patch`, `write` | Title row, LSP diagnostics | Diff or file preview |
| `read`, `grep`, `glob`, `find` | Title row | Body |

Error results of `edit`, `write`, `read`, `grep`, `glob`, and `find` render stock.

`install.ts` maps tools to views. Removing a line there leaves that tool's card stock.

## Design rules

These rules keep an omp update from hiding information or breaking a card. Keep them when changing a view.

- **Fail open.** A view returns `undefined` when it does not recognise a card's shape, and the card renders stock. `install.ts` also falls back to stock rows when a view throws, returns no rows, returns more rows than it was given, or returns a row wider than the pane. An omp change can make a card noisier, never emptier.
- **Never hide problems.** A row carrying omp's styled error or warning status glyph (`theme.styledSymbol("status.error" | "status.warning")`) always stays, as do the rows after it in the same box. This keeps LSP diagnostics. Do not match on the error color alone: diff removals and `-N` stats reuse it.
- **Read omp's styling, not its text.** Views match theme values (box glyphs, status glyphs, `getFgAnsi` colors) and section labels drawn by omp, never wording. Box glyphs come from `theme.boxRound`, so the Unicode, Nerd Font, and ASCII symbol presets all work.
- **Keep the component.** `install.ts` wraps each component in a `Proxy` that replaces only `render`. The framed-block marker, `describe`, `invalidate`, `releaseRenderCaches`, `dispose`, and input reach the original bound to itself, because `ToolCard` keeps state in private fields. The wrapper returns the same array while the stock rows are unchanged, which lets the TUI skip repaints.
- **Wrap once.** `install` stores omp's hooks under `Symbol.for("smolui.original")`, so a reload or a second session start never wraps a wrapper.

## omp surfaces it depends on

| Surface | Source in oh-my-pi | Used for |
| --- | --- | --- |
| `toolRenderers` registry and `ToolRenderer.renderCall`/`renderResult` | `packages/tui/src/tools/index.ts`, `renderer.ts` | Wrapping hooks per tool name |
| Framed card rows from `renderOutputBlock` | `packages/tui/src/render/output-block.ts` | Reading top, tee, body, and bottom rows |
| `Theme.boxRound`, `styledSymbol`, `getFgAnsi` | `packages/tui/src/theme/theme-class.ts` | Glyphs and colors views match |
| Bash card: `Output` section label, dim wrapped stats, warning truncation row | `packages/tui/src/tools/bash.ts` | `bash.ts` |
| Eval cell: code under the title bar, `Output` section, error-colored traceback | `packages/tui/src/tools/eval.ts` | `eval.ts` |
| Diagnostics tree from `formatDiagnostics` | `packages/tui/src/render/render-utils.ts` | Kept rows in `edit`/`write` |
| `ctx.mode`, `ctx.ui.notify` | `packages/coding-agent/src/extensibility/extensions/types.ts` | TUI gate, missing-renderer warning |

When omp drops a renderer that smolui maps, the TUI shows `smolui: no omp renderer for <tools>; those cards stay stock` at session start.

## Check after an omp update

[`docs/maintenance.md`](../../../../../docs/maintenance.md#omp-smolui) has the procedure.
