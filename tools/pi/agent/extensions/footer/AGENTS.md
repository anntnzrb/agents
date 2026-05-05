# Footer Extension

## Purpose
Replace Pi's built-in footer with a minimal one-line footer.

## Files
- `index.ts` — installs a custom footer via `ctx.ui.setFooter(...)`
- `tsconfig.json` — strict TS config matching sibling extensions

## Layout
- left: pi version prefix + shortened cwd + git branch
- right: context usage + model/thinking

## Invariants
- Interactive UI only
- No tools
- No widgets
- No extension status rows
- Re-renders on git branch changes

## Stop Rules
- Keep this extension footer-rendering scoped.
- Do not inject model-visible context or tool behavior from the footer.
