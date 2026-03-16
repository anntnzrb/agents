---
name: emacs
description: "Operate Emacs as both a running editor/runtime and a configurable system. Use this whenever the user mentions Emacs, Emacs Lisp, init.el, early-init.el, packages, use-package, package.el, hooks, advice, keybindings, themes, faces, fonts, buffers, windows, frames, server/emacsclient, or wants to inspect, configure, debug, or live-patch a running Emacs instance. Prefer runtime introspection and persistent config edits over guesswork or session-only tweaks."
compatibility: "Requires `emacsclient` and `uv`. Best with a running Emacs server. `info` preferred for manuals; `rg` recommended for installed docs/source lookup."
---

# Emacs

Treat Emacs work as two connected systems:
- the running Emacs state
- the persistent config on disk

Prefer truth from the running instance first, then official manuals, then local installed docs/source, then ecosystem corroboration.

## Evidence order
1. Runtime introspection via `scripts/emacsctl.py`
2. Official manuals via `info`
3. Local installed docs/source via `rg`
4. Corroboration via Grep.app, then `gh`

Avoid cloning Emacs unless explicitly needed.

## Workflow
1. Inspect runtime state first
2. Inspect the relevant config files only as needed
3. Pick the right persistence target
4. Preview the intended change if a live preview is useful
5. Apply the persistent edit
6. Apply live when safe
7. Verify both runtime state and file state
8. Call out restart requirements explicitly
9. Write the requested artifact if the user asked for one

Default pattern: inspect -> preview -> apply -> verify.

## Output discipline
- If the user asked for a report, note, patch file, or any other artifact at a specific path, create it before finalizing
- Do not stop at an acknowledgement, plan, or partial progress update when the task asked for a concrete deliverable
- After writing the requested artifact, summarize the result briefly

## Persistence targets
- `early-init.el`
  - startup behavior
  - frame/UI defaults that should exist before normal init
  - package activation knobs that must happen before init
  - many changes require restart to fully apply
- `init.el`
  - packages, `use-package`, modes, hooks, keybindings, runtime config
  - many changes can be reloaded live with `load-file`
- modular config file
  - if the repo already splits config, edit the relevant module instead of bloating `init.el`

## Runtime introspection
Default to `scripts/emacsctl.py` for Emacs communication. It exists to avoid fragile shell quoting and to make common checks easy.

Use raw `emacsclient` only when:
- debugging the helper itself
- the helper is unavailable
- a truly tiny one-off probe is simpler and there is no quoting risk

Prefer helper subcommands before custom Elisp when they fit the task:
- `ping`
- `face`
- `buffer`
- `key`
- `library`
- `feature`
- `reload-init`
- `load`

Commands below are shown relative to the skill directory. If your current working directory is elsewhere, resolve the absolute script path from this skill location and use that path.

Quick checks:

```bash
uv run scripts/emacsctl.py ping
uv run scripts/emacsctl.py face default
uv run scripts/emacsctl.py buffer
uv run scripts/emacsctl.py library use-package
uv run scripts/emacsctl.py feature server
```

For reusable or multiline queries, prefer a temp `.el` file plus `eval-file`.

## Official manuals
Prefer `info` for official semantics and version-matched behavior.

Useful nodes:
- `(emacs)Init File`
- `(emacs)Package Installation`
- `(emacs)Fonts`
- `(elisp)Named Features`
- `(elisp)Faces`
- `(elisp)Frame Parameters`
- `(use-package)Top`
- `(use-package)Installing packages`

If `info` is unavailable, grep the local manual files. In Nix environments, `nix shell nixpkgs#texinfoInteractive -c info ...` is a convenient fallback.

## Local installed docs/source
Use runtime queries to find the active Emacs installation, data dir, and library paths. Then search those paths with `rg`.

Use this layer for:
- implementation details
- clarifying ambiguous manual wording
- version-matched source inspection without cloning

## Corroboration
Use public search only after the first three layers.
- Grep.app: public usage patterns and config snippets
- `gh search code`: repo-targeted corroboration

Use corroboration to understand how people do things in practice, not as the primary source of truth for core Emacs behavior.

## Safe live-change pattern
- Make the intended file change first for persistent behavior
- Then apply live only to preview or verify the persistent change
- Prefer precise reloads:
  - the edited module file
  - `user-init-file`
  - `scripts/emacsctl.py reload-init`
  - `scripts/emacsctl.py load path/to/file.el`
- If the change lives in `early-init.el`, explain which parts are startup-only and whether a restart is required
- If you test an ephemeral tweak before writing it, label it clearly as a preview and persist it before finishing

## Package and dependency policy
- Package-manager side effects are opt-in only
- Do not run `package-refresh-contents`, `package-install`, upgrades, or archive rewrites unless the user asked for installs/upgrades or the task explicitly requires them and you explain why
- When modernizing old package bootstrap, preserve low-risk preference settings such as archive URLs or package policy variables unless there is a good reason to remove them
- Prefer built-in Emacs features when adequate
- On modern Emacs, verify bundled features from runtime/docs before bootstrapping external packages

## Guardrails
- Do not trust memory alone for Emacs semantics; inspect runtime/docs/source
- Do not assume a specific config layout, package set, theme, keybinding scheme, or distro integration; inspect first
- Do not claim a startup-only change is live if it only fully applies on restart
- Do not leave persistent intent as a session-only tweak unless the user asked for a temporary experiment
- Keep diffs small and modular; avoid turning `init.el` into a dump file
- Verify final state with runtime queries after reloading
- Prefer querying variables, faces, frame params, keymaps, loaded features, and buffer state over guessing
- Prefer `scripts/emacsctl.py` over raw `emacsclient` when the helper can express the same operation reliably
- Be explicit about risk when live-evaluating changes in an already-running Emacs

## Resources
- `scripts/emacsctl.py`: reliable `emacsclient` wrapper
- `references/live-workflow.md`: inspect/apply/verify guidance and restart matrix
- `references/common-queries.md`: reusable runtime query examples
- create task-specific evals only when intentionally benchmarking this skill with `skill-creator`
