---
disable-model-invocation: true
name: clip
description: "Use to copy terminal output, files, or stdin to the clipboard via OSC 52 across macOS, Linux, Windows, and SSH/tmux."
license: AGPL-3.0-or-later
metadata:
  author: anntnzrb
---

# OSC 52 clipboard copier

Copy a file or stdin to the host clipboard using the OSC 52 escape sequence. Works from terminals, SSH sessions, tmux, and Windows consoles without a native clipboard API.

## When to use

- The user asks to copy output, a file, or a snippet to the clipboard.
- The agent is in a terminal, SSH session, or tmux pane and cannot call a GUI clipboard manager.
- The destination is the local terminal's host clipboard.

## Public entrypoint

```text
python3 <skill-dir>/scripts/cli.py [FILE]
```

- `FILE`: optional path to copy. Reads from stdin if omitted.
- Emits the OSC 52 sequence to the active terminal output.

## Common calls

```text
# copy a file
python3 <skill-dir>/scripts/cli.py ./key.pem

# copy command output
some-command | python3 <skill-dir>/scripts/cli.py

# copy stdin (type or paste, then Ctrl-D)
python3 <skill-dir>/scripts/cli.py
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
