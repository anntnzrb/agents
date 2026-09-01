#!/usr/bin/env python3
# Copyright (c) 2026
"""Copy stdin or a file to the host clipboard via OSC 52."""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path
from typing import BinaryIO


def arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Copy stdin or a file to the host clipboard via OSC 52.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        metavar="FILE",
        help="file to copy; reads from stdin if omitted",
    )
    return parser.parse_args()


def read_input(path: str | None) -> bytes:
    """Read content from a file or stdin."""
    if path is None:
        return sys.stdin.buffer.read()

    return Path(path).read_bytes()


def get_output_channel() -> tuple[BinaryIO, bool]:
    """Return the best output channel and whether it is the outer SSH TTY."""
    if os.name == "nt":
        try:
            return Path("CONOUT$").open("wb", buffering=0), False
        except OSError:
            return sys.stdout.buffer, False

    ssh_tty = os.environ.get("SSH_TTY")
    if ssh_tty and Path(ssh_tty).exists():
        try:
            fd = os.open(ssh_tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
            return os.fdopen(fd, "wb", buffering=0), True
        except OSError:
            pass

    for candidate in ("/dev/tty",):
        if not Path(candidate).exists():
            continue
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
            return os.fdopen(fd, "wb", buffering=0), False
        except OSError:
            continue

    return sys.stdout.buffer, False


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
        sys.stderr.write(f"clip: not a file: {args.file}\n")
        return 2

    data = read_input(args.file)
    if not data:
        return 0

    target, is_outer_tty = get_output_channel()
    use_tmux = os.environ.get("TMUX") is not None and not is_outer_tty
    osc = build_osc52(data, use_tmux_passthrough=use_tmux)

    try:
        target.write(osc)
        target.flush()
    except OSError as exc:
        sys.stderr.write(f"clip: write failed: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
