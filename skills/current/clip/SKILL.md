---
name: clip
description: "Use when copying output, files, or stdin to the system clipboard; not for web pastebin uploads."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# Clipboard copier

Copy a file or stdin to the client clipboard. The script selects a native tool locally and OSC 52 over SSH.

## When to use

- The user asks to copy output, a file, or a snippet to the clipboard.
- The destination is the clipboard on the computer running the terminal client.
- Use this entrypoint without asking the user to select a platform or transport.

## Public entrypoint

```text
uv run --script <skill-dir>/scripts/cli.py [FILE]
```

- `FILE`: optional path to copy. Reads from stdin if omitted.
- Emits the OSC 52 sequence to the active terminal output.

## Common calls

```text
# copy a file
uv run --script <skill-dir>/scripts/cli.py ./key.pem

# copy command output
some-command | uv run --script <skill-dir>/scripts/cli.py

# copy stdin (type or paste, then Ctrl-D)
uv run --script <skill-dir>/scripts/cli.py
```

## Platform notes

- **macOS / Linux**: writes to `SSH_TTY` or `/dev/tty` first, then falls back to `stdout`.
- **Windows**: opens `CONOUT$`, then falls back to `stdout`.
- **tmux**: detects `TMUX` and wraps the sequence in tmux DCS passthrough unless the output goes directly to the outer SSH TTY.
- The terminal must support OSC 52 for the copy to reach the host clipboard.

## Exit codes

- `0`: success
- `1`: write or runtime error
- `2`: usage or file error

## Empty input

Empty input is a no-op. The script does not emit an empty OSC 52 sequence, so it never clears the host clipboard.
