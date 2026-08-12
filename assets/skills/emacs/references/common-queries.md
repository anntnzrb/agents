# Common queries

Use with `scripts/emacsctl.py`. Structured output: alist with string keys; use `--json`. Commands are relative to the skill directory; elsewhere resolve `<skill-dir>/scripts/cli.py` absolutely.

## Runtime

```bash
uv run --script <skill-dir>/scripts/cli.py ping
```

## Faces

```bash
uv run --script <skill-dir>/scripts/cli.py face default
uv run --script <skill-dir>/scripts/cli.py face fixed-pitch
uv run --script <skill-dir>/scripts/cli.py face variable-pitch
```

Combined query: write to `<temp-dir>/emacs-query.el`:

```elisp
(list
  (cons "default_family" (face-attribute 'default :family nil 'default))
  (cons "default_height" (face-attribute 'default :height nil 'default))
  (cons "fixed_pitch_family" (face-attribute 'fixed-pitch :family nil 'default))
  (cons "fixed_pitch_height" (face-attribute 'fixed-pitch :height nil 'default))
  (cons "variable_pitch_family" (face-attribute 'variable-pitch :family nil 'default))
  (cons "variable_pitch_height" (face-attribute 'variable-pitch :height nil 'default))
  (cons "frame_font" (or (frame-parameter nil 'font) "")))
```

## Buffer

```bash
uv run --script <skill-dir>/scripts/cli.py buffer
```

## Keybinding

```bash
uv run --script <skill-dir>/scripts/cli.py key 'C-x C-f'
```

## Features and libraries

```bash
uv run --script <skill-dir>/scripts/cli.py feature server
uv run --script <skill-dir>/scripts/cli.py library package
uv run --script <skill-dir>/scripts/cli.py library use-package
```

## Variables

If no helper exists, write to `<temp-dir>/emacs-query.el`:

```elisp
(list
  (cons "inhibit_startup_message" inhibit-startup-message)
  (cons "use_dialog_box" use-dialog-box)
  (cons "package_enable_at_startup" package-enable-at-startup))
```

## Mode state

Write to `<temp-dir>/emacs-query.el`:

```elisp
(list
  (cons "menu_bar_mode" (bound-and-true-p menu-bar-mode))
  (cons "tool_bar_mode" (bound-and-true-p tool-bar-mode))
  (cons "scroll_bar_mode" (bound-and-true-p scroll-bar-mode))
  (cons "blink_cursor_mode" (bound-and-true-p blink-cursor-mode)))
```

## Docs/source roots

Write to `<temp-dir>/emacs-query.el`, then search locally with `rg`:

```elisp
(list
  (cons "data_directory" data-directory)
  (cons "invocation_directory" invocation-directory)
  (cons "info_directories" Info-directory-list)
  (cons "package_library" (or (locate-library "package") "")))
```

Run every query file with:

```text
uv run --script <skill-dir>/scripts/cli.py eval-file <temp-dir>/emacs-query.el --json
```

## Eval from file

For larger forms, write to `<temp-dir>/emacs-query.el`:

```elisp
(list
  (cons "default_family" (face-attribute 'default :family nil 'default))
  (cons "default_height" (face-attribute 'default :height nil 'default)))
```

## Reload init

```bash
uv run --script <skill-dir>/scripts/cli.py reload-init
```

Or load a specific file:

```bash
uv run --script <skill-dir>/scripts/cli.py load path/to/init.el
```

Live loading does not activate every startup-time behavior; verify and call out restart requirements.
