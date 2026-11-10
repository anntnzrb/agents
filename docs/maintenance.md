# Maintain harness customizations

Some harness sources hook into internals that upstream may change in any release. This page lists the checks to run after a harness package update. Design and behavior stay in each customization's own documentation under `harnesses/`.

## omp smolui

[smolui](../harnesses/omp/agent/extensions/smolui/README.md) restyles omp's built-in tool cards. It fails open: when an omp release changes a card it does not recognise, that card renders stock. An update therefore shows up as noisier cards or a session-start warning, not as missing information. Run this check after omp updates to confirm each view still applies.

### Find the installed omp version

omp's extension packages live in the generated home:

```bash
jq -r .version ~/.omp/agent/node_modules/@oh-my-pi/pi-tui/package.json
```

The upstream source is checked out read-only at `~/src/vendored/github.com/can1357/oh-my-pi`. Compare it against the installed version with `git -C ~/src/vendored/github.com/can1357/oh-my-pi log -1 --format=%s`.

### Review upstream changes

List the commits that touched the surfaces smolui depends on since the last version you checked:

```bash
cd ~/src/vendored/github.com/can1357/oh-my-pi
git log --oneline v<last-checked>..v<installed> -- \
  packages/tui/src/tools/index.ts \
  packages/tui/src/tools/renderer.ts \
  packages/tui/src/tools/bash.ts \
  packages/tui/src/tools/eval.ts \
  packages/tui/src/render/output-block.ts \
  packages/tui/src/render/tool-card.ts \
  packages/tui/src/theme/theme-class.ts
```

The [dependency table](../harnesses/omp/agent/extensions/smolui/README.md#omp-surfaces-it-depends-on) maps each path to the view it affects.

### Check the TUI

Start `omp` in a scratch directory and ask it to run these calls:

1. A `bash` command that prints several lines, and one that exits non-zero.
2. A Python `eval` cell that succeeds, and one that raises.
3. A `read`, a `grep`, and a `glob`.
4. An `edit` that introduces a type error in a TypeScript file, so LSP reports a diagnostic.

Compare each collapsed card with the [card table](../harnesses/omp/agent/extensions/smolui/README.md#what-each-card-keeps), then press ctrl+o to confirm the expanded card is stock. A card that shows its full stock body while collapsed has a view that no longer recognises omp's layout; adjust that view.

### Type-check against the installed packages

```bash
T=$(mktemp -d) && cp harnesses/omp/agent/extensions/smolui/*.ts "$T" \
  && ln -s ~/.omp/agent/node_modules "$T/node_modules" \
  && (cd "$T" && bunx tsc --noEmit --allowImportingTsExtensions --module preserve \
       --moduleResolution bundler --target esnext --strict --skipLibCheck \
       --types node index.ts)
```

A type error names an omp API that changed shape.

### Disable smolui

To fall back to stock cards while a view is being fixed, add `extension-module:smolui` to `disabledExtensions` in [`harnesses/omp/agent/config.yml`](../harnesses/omp/agent/config.yml), then sync.
