# Live workflow

Emacs work has two layers: runtime state in the running Emacs; persistent config on disk. Goal: persistent change, verified against the live instance when safe.

## Evidence stack
Use this order unless a strong reason not to:

1. Runtime introspection:
   - `uv run --script <skill-dir>/scripts/cli.py ping`
   - `uv run --script <skill-dir>/scripts/cli.py face default`
   - `uv run --script <skill-dir>/scripts/cli.py buffer`
   - `uv run --script <skill-dir>/scripts/cli.py key 'C-x C-f'`
   - `uv run --script <skill-dir>/scripts/cli.py library package`
   - `uv run --script <skill-dir>/scripts/cli.py feature server`
   - `uv run --script <skill-dir>/scripts/cli.py eval ...`
2. Official manuals:
   - `info '(emacs)Init File'`
   - `info '(elisp)Faces'`
   - `info '(elisp)Named Features'`
   - `info '(use-package)Top'`
3. Local installed docs/source: use runtime state to locate the active Emacs install; search local manuals and Lisp source with `rg`.
4. Public corroboration: Grep.app for broad usage patterns; `gh search code` for repo-specific corroboration.

Avoid cloning unless the task explicitly needs it. Commands above are relative to the skill directory; elsewhere, resolve and use the absolute script path.

## Inspect → preview → apply → verify

### Inspect
Establish:
- current truth in the running Emacs
- file that should own the behavior
- startup-time versus runtime behavior

Query as useful:
- Emacs version; server status
- `user-init-file`; `early-init-file`
- active face/font/mode/keymap value
- whether a feature is loaded
- file providing the library

### Preview
Before persistent edits, assess whether a quick live preview is useful.

Good previews: face/font changes; keybindings; mode toggles; cosmetic UI.
Bad previews: package bootstrapping; startup-order changes; large structural refactors; anything risky enough that partial live application would confuse the session.

A preview is not final until the file change exists.

### Apply
Apply the persistent change to the narrowest correct target:
- `early-init.el`: startup behavior and pre-init frame/package knobs
- `init.el`: normal package/runtime config
- existing module file: already-split config

Keep edits small, coherent, and easy to verify.

### Verify
Verify both:
- file level: intended config exists on disk
- runtime level: live Emacs reflects intended state, or restart requirement is stated

Examples: face family/height changed; mode enabled; variable value updated; key binding resolves to intended command; feature loaded from intended place.

## Restart matrix
Usually safe to apply live: many face and font changes; mode toggles; most `setq` values in normal init; keybindings; hooks and advice added in normal init; theme changes.

Often needs care: package setup that changes load ordering; anything that relies on startup sequence; frame defaults for future frames versus current frame state; changing `default-frame-alist`.

Often restart-required for full effect: startup-message and splash behavior; early package activation choices; many `early-init.el` changes; startup frame parameters that only matter before the first frame is created.

When in doubt, state:
- what changed live now
- what still needs a restart

## Package-side-effect policy
Package installation and archive refresh are not harmless defaults. Do not automatically:
- refresh archives
- install packages
- upgrade packages
- rewrite package manager setup

Do these only when:
- the user asked for it
- the task truly requires it
- the side effect is explained first

When cleaning up legacy bootstrap code, preserve low-risk preference settings such as archive URLs or non-install policy knobs unless there is a strong reason to simplify them away. For modern Emacs, confirm built-in features before bootstrapping external copies.

## Modern `use-package`
For modern Emacs releases, verify runtime state and official manuals before assuming a bootstrap recipe. Check:
- whether `use-package` is already shipped
- whether explicit `package-initialize` is still needed
- whether the config intends package side effects at startup

## Local docs/source lookup without cloning
Prefer the installed copy that matches the running Emacs. Query:
- `data-directory`
- `invocation-directory`
- `locate-library`
- `Info-directory-list`

Search those paths with `rg`; this is usually more reliable than searching `master` on the web.

## Output discipline
For a requested artifact such as a report file, patch file, or notes path:
- create it explicitly
- do not stop after a progress update
- summarize after it exists

## Communication
On completion, state explicitly:
- file changed
- what was applied live
- what was only persisted for next restart
- what was verified
- remaining restart requirement or risk
