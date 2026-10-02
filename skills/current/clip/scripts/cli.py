#!/usr/bin/env python3
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
# Copyright (c) 2026
"""Copy stdin or a file using a native clipboard tool or OSC 52."""

import argparse
import base64
import os
import shutil
import subprocess
import sys
from contextlib import closing, nullcontext
from pathlib import Path
from typing import BinaryIO


class _Args(argparse.Namespace):
    file: str | None = None


def arguments() -> _Args:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Copy stdin or a file to the client clipboard automatically.",
    )
    _ = parser.add_argument(
        "file",
        nargs="?",
        metavar="FILE",
        help="file to copy; reads from stdin if omitted",
    )
    return parser.parse_args(namespace=_Args())


def read_input(path: str | None) -> bytes:
    """Read content from a file or stdin."""
    if path is None:
        return sys.stdin.buffer.read()

    return Path(path).read_bytes()


def native_command() -> list[str] | None:
    """Select a local clipboard tool; never copy to an SSH server's clipboard."""
    if any(os.environ.get(key) for key in ("SSH_TTY", "SSH_CONNECTION", "SSH_CLIENT")):
        return None

    candidates: list[list[str]] = []
    if sys.platform == "darwin":
        candidates = [["pbcopy"]]
    elif os.name == "nt" or os.environ.get("WSL_DISTRO_NAME"):
        script = (
            "$ErrorActionPreference = 'Stop'; "
            "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new(); "
            "Set-Clipboard -Value ([Console]::In.ReadToEnd())"
        )
        candidates = [
            [tool, "-NoProfile", "-NonInteractive", "-Command", script]
            for tool in ("pwsh", "powershell", "powershell.exe")
        ]
    else:
        if os.environ.get("WAYLAND_DISPLAY"):
            candidates.append(["wl-copy"])
        if os.environ.get("DISPLAY"):
            candidates.extend(
                [
                    ["xclip", "-selection", "clipboard"],
                    ["xsel", "--clipboard", "--input"],
                ]
            )

    for command in candidates:
        if executable := shutil.which(command[0]):
            return [executable, *command[1:]]
    return None


def ancestor_terminals() -> list[str]:
    """Find ancestor TTYs when the agent detached its command subprocess."""
    terminals: list[str] = []
    pid = os.getppid()
    seen: set[int] = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "ppid=", "-o", "tty="],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
            )
        except OSError, subprocess.SubprocessError:
            break
        fields = result.stdout.split()
        if not fields or not fields[0].isdigit():
            break
        match fields:
            case [parent, tty]:
                pid = int(parent)
            case _:
                break
        if tty not in ("?", "??", "-"):
            terminals.append(tty if tty.startswith("/dev/") else f"/dev/{tty}")
    return terminals


def get_output_channel() -> tuple[BinaryIO, bool]:
    """Open a terminal, never silently emit OSC 52 into captured output."""
    if os.name == "nt":
        return Path("CONOUT$").open("wb", buffering=0), False

    ssh_tty = os.environ.get("SSH_TTY")
    candidates = [(ssh_tty, True)] if ssh_tty else []
    candidates.append(("/dev/tty", False))
    for candidate, is_outer in candidates:
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_NOCTTY)
            if not os.isatty(fd):
                os.close(fd)
                continue
            return os.fdopen(fd, "wb"), is_outer
        except OSError:
            continue

    for candidate in ancestor_terminals():
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_NOCTTY)
            if not os.isatty(fd):
                os.close(fd)
                continue
            return os.fdopen(fd, "wb"), False
        except OSError:
            continue

    if sys.stdout.isatty():
        return sys.stdout.buffer, False
    raise OSError("no accessible terminal or native clipboard backend")


def build_osc52(payload: bytes, *, use_tmux_passthrough: bool) -> bytes:
    """Build an OSC 52 sequence, with tmux passthrough if needed."""
    b64 = base64.b64encode(payload).decode("ascii")
    osc = f"\x1b]52;c;{b64}\x07".encode("ascii")
    if use_tmux_passthrough:
        osc = f"\x1bPtmux;\x1b\x1b]52;c;{b64}\x07\x1b\\".encode("ascii")
    return osc


def main() -> int:
    """Copy input to the clipboard and return the documented status."""
    args = arguments()

    if args.file is not None and not Path(args.file).is_file():
        _ = sys.stderr.write(f"clip: not a file: {args.file}\n")
        return 2

    data = read_input(args.file)
    if not data:
        return 0

    target, is_outer_tty = get_output_channel()
    use_tmux = os.environ.get("TMUX") is not None and not is_outer_tty
    osc = build_osc52(data, use_tmux_passthrough=use_tmux)

    try:
        _ = target.write(osc)
        target.flush()
    except OSError as exc:
        _ = sys.stderr.write(f"clip: write failed: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
