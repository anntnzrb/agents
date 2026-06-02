# Live workflow

Use this reference when you need the detailed Emacs operating pattern behind the main skill.

## Core model

Treat Emacs work as two related layers:

- runtime state in the currently running Emacs
- persistent config on disk

The goal is usually not a one-off tweak. The goal is a persistent change that is also verified against the live instance when safe.

## Evidence stack

Use this order unless there is a strong reason not to:

1. Runtime introspection
   - `uv run --script <skill-dir>/scripts/cli.py ping`
   - `uv run --script <skill-dir>/scripts/cli.py face default`
   - `uv run --script <skill-dir>/scripts/cli.py buffer`
   - `uv run --script <skill-dir>/scripts/cli.py key 'C-x C-f'`
   - `uv run --script <skill-dir>/scripts/cli.py library package`
   - `uv run --script <skill-dir>/scripts/cli.py feature server`
   - `uv run --script <skill-dir>/scripts/cli.py eval ...`
2. Official manuals
   - `info '(emacs)...'`
   - `info '(elisp)...'`
   - `info '(use-package)...'`
3. Local installed docs/source
   - use runtime state to locate the active Emacs install
   - search local manuals and Lisp source with `rg`
4. Public corroboration
   - Grep.app for broad usage patterns
   - `gh search code` for repo-specific corroboration

Avoid cloning unless the task explicitly needs it.

Commands above are shown relative to the skill directory. When the working directory is elsewhere, resolve and use the absolute script path.

## Inspect -> preview -> apply -> verify

### Inspect

Start by answering:

- what is true in the running Emacs right now?
- which file should own this behavior?
- is the behavior startup-time or runtime?

Useful runtime questions:

- what Emacs version is this?
- is the server running?
- what are `user-init-file` and `early-init-file`?
- what face/font/mode/keymap value is active?
- is a feature already loaded?
- which file provides this library?

### Preview

Before changing persistent files, decide whether a quick live preview is useful.

Good preview candidates:

- face/font changes
- keybinding changes
- mode toggles
- cosmetic UI changes

Bad preview candidates:

- package bootstrapping
- startup ordering changes
- large structural refactors
- anything risky enough that a live partial application would confuse the session

If you preview first, call it a preview. Do not present it as the final result until the file change exists.

### Apply

Apply the persistent file change in the right place.

Choose the narrowest correct target:

- `early-init.el` for startup behavior and pre-init frame/package knobs
- `init.el` for normal package/runtime config
- an existing module file if the config is already split

Keep edits small, coherent, and easy to verify.

### Verify

Verification should happen in both places:

- file level: the intended config exists on disk
- runtime level: the live Emacs reflects the intended state, or you clearly state that restart is required

Examples of verification:

- face family/height changed
- mode enabled
- variable value updated
- key binding resolves to the intended command
- feature loaded from the intended place

## Restart matrix

### Usually safe to apply live

- many face and font changes
- mode toggles
- most `setq` values in normal init
- keybindings
- hooks and advice added in normal init
- theme changes

### Often needs care

- package setup that changes load ordering
- anything that relies on startup sequence
- frame defaults for future frames versus current frame state
- changing `default-frame-alist`

### Often restart-required for full effect

- startup-message and splash behavior
- early package activation choices
- many `early-init.el` changes
- startup frame parameters that only matter before the first frame is created

When in doubt, say:

- what changed live now
- what still needs a restart

## Package-side-effect policy

Package installation and archive refresh are not harmless defaults.

Do not automatically:

- refresh archives
- install packages
- upgrade packages
- rewrite package manager setup

Only do those when:

- the user asked for it
- the task truly requires it
- you explain the side effect first

When cleaning up legacy bootstrap code, preserve low-risk preference settings such as archive URLs or non-install policy knobs unless there is a strong reason to simplify them away.

For modern Emacs, confirm built-in features before bootstrapping external copies.

## Modern `use-package` stance

For modern Emacs releases, verify the current situation from runtime state and official manuals before assuming a bootstrap recipe.

Check:

- whether `use-package` is already shipped
- whether explicit `package-initialize` is still needed
- whether the config intends package side effects at startup

## Local docs/source lookup without cloning

Prefer the installed copy that matches the running Emacs.

Useful runtime facts to query:

- `data-directory`
- `invocation-directory`
- `locate-library`
- `Info-directory-list`

Then search those paths with `rg`.

This is usually more reliable than searching `master` on the web.

## Output discipline

When the user requested an artifact such as a report file, patch file, or notes path:

- create it explicitly
- do not stop after a progress update
- summarize after the artifact exists

## Communication style

When finishing an Emacs task, be explicit about:

- what file changed
- what was applied live
- what was only persisted for next restart
- what was verified
- any remaining restart requirement or risk
