---
name: emacs
description: Inspect, configure, debug, or automate Emacs, Emacs Lisp, init.el, packages, and runtime state.
license: GPL-3.0-or-later
compatibility: Requires `emacsclient` and `uv`. Best with a running Emacs server. `info` preferred for manuals; `rg` recommended for installed docs/source lookup.
metadata:
  author: anntnzrb

---

# Emacs

Emacs work: running state + persistent config on disk. Prefer evidence in order: running instance; official manuals via `info`; local installed docs/source via `rg`; ecosystem corroboration via Grep.app, then `gh`. Avoid cloning Emacs unless explicitly needed.

## Entry point

Cross-platform command:

```text
uv run --script <skill-dir>/scripts/cli.py ...
```

Set `<skill-dir>` to this skill directory. Do not rely on shell sourcing, executable bits, or shebang dispatch.

## Required reads

- Any persistent or live Emacs change → read `references/live-workflow.md` for inspect, preview, persist, and verify.
- Querying faces, buffers, keys, features, or paths → read `references/common-queries.md` for exact runtime query recipes.

## Workflow

1. Inspect runtime state first.
2. Inspect relevant config files only as needed.
3. Pick the right persistence target.
4. Preview the intended change if a live preview is useful.
5. Apply the persistent edit.
6. Apply live when safe.
7. Verify runtime state and file state.
8. Call out restart requirements explicitly.
9. Write the requested artifact if the user asked for one.

Default: inspect → preview → apply → verify.

## Output discipline

- A requested report, note, patch file, or other artifact at a specific path MUST be created before finalizing.
- When a concrete deliverable is requested, do not stop at acknowledgement, plan, or partial progress.
- After writing the artifact, summarize the result briefly.

## Runtime introspection

Default Emacs communication: `uv run --script <skill-dir>/scripts/cli.py`; it dispatches to `scripts/emacsctl.py`, avoids fragile shell quoting, and simplifies common checks.

Use raw `emacsclient` only when debugging the helper, the helper is unavailable, or a truly tiny one-off probe is simpler with no quoting risk.

Prefer helper subcommands over custom Elisp when they fit: `ping`, `face`, `buffer`, `key`, `library`, `feature`, `reload-init`, `load`.

Quick checks:

```bash
uv run --script <skill-dir>/scripts/cli.py ping
uv run --script <skill-dir>/scripts/cli.py face default
uv run --script <skill-dir>/scripts/cli.py buffer
uv run --script <skill-dir>/scripts/cli.py library use-package
uv run --script <skill-dir>/scripts/cli.py feature server
```

For reusable or multiline queries, prefer a temporary `.el` file plus `eval-file`.

## Guardrails

- Do not trust memory alone for Emacs semantics; inspect runtime, docs, or source.
- Do not assume a config layout, package set, theme, keybinding scheme, or distro integration; inspect first.
- Do not claim a startup-only change is live when it only fully applies on restart.
- Do not leave persistent intent as a session-only tweak unless the user requested a temporary experiment.
- Package-manager writes require explicit user intent.
- Keep diffs small and modular; do not turn `init.el` into a dump file.
- After reloading, verify final state with runtime queries.
- Prefer querying variables, faces, frame params, keymaps, loaded features, and buffer state over guessing.
- Prefer `uv run --script <skill-dir>/scripts/cli.py` over raw `emacsclient` when the helper can express the same operation reliably.
- Be explicit about risk when live-evaluating changes in an already-running Emacs.
