# Common queries

Use these with `scripts/emacsctl.py`. For structured output, return an alist with string keys and use `--json`.

Commands below are shown relative to the skill directory. When the working directory is elsewhere, resolve and use the absolute script path.

## Runtime basics

```bash
uv run --script <skill-dir>/scripts/cli.py ping
```

## Active fonts and faces

```bash
uv run --script <skill-dir>/scripts/cli.py face default
uv run --script <skill-dir>/scripts/cli.py face fixed-pitch
uv run --script <skill-dir>/scripts/cli.py face variable-pitch
```

For a combined query:

```bash
cat <<'ELISP' | uv run --script <skill-dir>/scripts/cli.py eval - --json
(list
  (cons "default_family" (face-attribute 'default :family nil 'default))
  (cons "default_height" (face-attribute 'default :height nil 'default))
  (cons "fixed_pitch_family" (face-attribute 'fixed-pitch :family nil 'default))
  (cons "fixed_pitch_height" (face-attribute 'fixed-pitch :height nil 'default))
  (cons "variable_pitch_family" (face-attribute 'variable-pitch :family nil 'default))
  (cons "variable_pitch_height" (face-attribute 'variable-pitch :height nil 'default))
  (cons "frame_font" (or (frame-parameter nil 'font) "")))
ELISP
```

## Current buffer context

```bash
uv run --script <skill-dir>/scripts/cli.py buffer
```

## Keybinding lookup

```bash
uv run --script <skill-dir>/scripts/cli.py key 'C-x C-f'
```

## Feature and library lookup

```bash
uv run --script <skill-dir>/scripts/cli.py feature server
uv run --script <skill-dir>/scripts/cli.py library package
uv run --script <skill-dir>/scripts/cli.py library use-package
```

## Variable values

Use a custom eval when there is no dedicated helper subcommand yet:

```bash
cat <<'ELISP' | uv run --script <skill-dir>/scripts/cli.py eval - --json
(list
  (cons "inhibit_startup_message" inhibit-startup-message)
  (cons "use_dialog_box" use-dialog-box)
  (cons "package_enable_at_startup" package-enable-at-startup))
ELISP
```

## Mode state

```bash
cat <<'ELISP' | uv run --script <skill-dir>/scripts/cli.py eval - --json
(list
  (cons "menu_bar_mode" (bound-and-true-p menu-bar-mode))
  (cons "tool_bar_mode" (bound-and-true-p tool-bar-mode))
  (cons "scroll_bar_mode" (bound-and-true-p scroll-bar-mode))
  (cons "blink_cursor_mode" (bound-and-true-p blink-cursor-mode)))
ELISP
```

## Locate docs/source roots

```bash
cat <<'ELISP' | uv run --script <skill-dir>/scripts/cli.py eval - --json
(list
  (cons "data_directory" data-directory)
  (cons "invocation_directory" invocation-directory)
  (cons "info_directories" Info-directory-list)
  (cons "package_library" (or (locate-library "package") "")))
ELISP
```

Then search locally with `rg`.

## Eval from file

For larger forms, prefer a temp file:

```bash
cat > <temp-dir>/emacs-query.el <<'ELISP'
(list
  (cons "default_family" (face-attribute 'default :family nil 'default))
  (cons "default_height" (face-attribute 'default :height nil 'default)))
ELISP

uv run --script <skill-dir>/scripts/cli.py eval-file <temp-dir>/emacs-query.el --json
```

## Reload the current init file

```bash
uv run --script <skill-dir>/scripts/cli.py reload-init
```

Or load a specific file:

```bash
uv run --script <skill-dir>/scripts/cli.py load path/to/init.el
```

Remember: loading a file live does not mean every startup-time behavior is now active. Verify and call out restart requirements.
