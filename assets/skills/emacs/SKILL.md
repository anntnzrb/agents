---
name: emacs
description: Inspect, configure, debug, or automate Emacs, Emacs Lisp, init.el, packages, and runtime state.
license: GPL-3.0-or-later
compatibility: Requires `emacsclient` and `uv`. Best with a running Emacs server. `info` preferred for manuals; `rg` recommended for installed docs/source lookup.
metadata:
  author: anntnzrb

---

# Emacs

Treat Emacs work as two connected systems:

- the running Emacs state
- the persistent config on disk

Prefer truth from the running instance first, then official manuals, then local installed docs/source, then ecosystem corroboration.

## Entry point

Cross-platform:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

## Required follow-up reads

| Need | Read | When |
| --- | --- | --- |
| Inspect, preview, persist, and verify | `references/live-workflow.md` | Any persistent or live Emacs change |
| Exact runtime query recipes | `references/common-queries.md` | Querying faces, buffers, keys, features, or paths |

## Evidence order

1. Runtime introspection via `uv run --script <skill-dir>/scripts/cli.py`
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

## Runtime introspection

Default to `uv run --script <skill-dir>/scripts/cli.py` for Emacs communication. It dispatches to `scripts/emacsctl.py`, avoids fragile shell quoting, and makes common checks easy.

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

Quick checks:

```bash
uv run --script <skill-dir>/scripts/cli.py ping
uv run --script <skill-dir>/scripts/cli.py face default
uv run --script <skill-dir>/scripts/cli.py buffer
uv run --script <skill-dir>/scripts/cli.py library use-package
uv run --script <skill-dir>/scripts/cli.py feature server
```

For reusable or multiline queries, prefer a temp `.el` file plus `eval-file`.

## Guardrails

- Do not trust memory alone for Emacs semantics; inspect runtime/docs/source
- Do not assume a specific config layout, package set, theme, keybinding scheme, or distro integration; inspect first
- Do not claim a startup-only change is live if it only fully applies on restart
- Do not leave persistent intent as a session-only tweak unless the user asked for a temporary experiment
- Package-manager writes require explicit user intent
- Keep diffs small and modular; avoid turning `init.el` into a dump file
- Verify final state with runtime queries after reloading
- Prefer querying variables, faces, frame params, keymaps, loaded features, and buffer state over guessing
- Prefer `uv run --script <skill-dir>/scripts/cli.py` over raw `emacsclient` when the helper can express the same operation reliably
- Be explicit about risk when live-evaluating changes in an already-running Emacs
