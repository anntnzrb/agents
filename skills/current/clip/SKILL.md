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
- Read stderr for the selected transport and errors.
- If stderr reports OSC 52 sent, report that the sequence was sent. Do not claim clipboard acceptance was verified.
- If the command fails, report the error. Do not retry by printing escape sequences into captured output.

## Common calls

```text
# copy a file
uv run --script <skill-dir>/scripts/cli.py ./notes.txt

# copy command output
some-command | uv run --script <skill-dir>/scripts/cli.py

# copy stdin (type or paste, then Ctrl-D)
uv run --script <skill-dir>/scripts/cli.py
```

## Transport selection

- Local macOS uses `pbcopy`. Linux uses `wl-copy` for Wayland or `xclip` or `xsel` for X11 when available.
- Local Windows and WSL use PowerShell `Set-Clipboard` with UTF-8 stdin.
- SSH markers disable native tools so the script does not copy to the server's clipboard.
- If no native tool succeeds, the script tries OSC 52 through `SSH_TTY`, the controlling terminal, an ancestor terminal, or terminal-connected stdout. Windows uses `CONOUT$`.
- Detached agent commands discover ancestor terminals through `ps`. Captured stdout is never a clipboard transport.
- tmux and GNU screen get passthrough framing unless the script writes directly to the outer SSH TTY.
- OSC 52 requires terminal support and clipboard permissions. tmux must allow passthrough. Sending the sequence cannot confirm terminal acceptance.
- Remote execution without SSH markers cannot reliably identify the client clipboard. A detached remote process without an accessible terminal has no clipboard transport.

## Exit codes

- `0`: native tool succeeded, OSC 52 was sent, or empty input was skipped
- `1`: no usable transport, write error, or runtime error
- `2`: usage or file error
- Native tool exit codes are preserved if OSC 52 also fails.

## Empty input

Empty input is a no-op. The script does not emit an empty OSC 52 sequence, so it never clears the host clipboard.

## Validation

```text
uv run --script skills/current/skill-creator/scripts/cli.py gates skills/current/clip --tests
uv run --script skills/current/skill-creator/scripts/cli.py quick-validate skills/current/clip
```
