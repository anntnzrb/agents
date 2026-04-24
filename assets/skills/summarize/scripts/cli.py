#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Cross-platform wrapper for @steipete/summarize."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

PACKAGE = "@steipete/summarize"
OPTIONAL_BINS = [
    "yt-dlp",
    "ffmpeg",
    "tesseract",
    "whisper-cli",
    "claude",
    "codex",
    "gemini",
    "agent",
]
KEY_ENV_VARS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "Z_AI_API_KEY",
    "OPENROUTER_API_KEY",
    "NVIDIA_API_KEY",
    "FIRECRAWL_API_KEY",
    "APIFY_API_TOKEN",
    "FAL_KEY",
]

HELP = f"""summarize wrapper

Usage:
  uv run --script <skill-dir>/scripts/cli.py <summarize-args>...
  uv run --script <skill-dir>/scripts/cli.py doctor

Delegates non-doctor commands to:
  bun x {PACKAGE} <summarize-args>...

Examples:
  uv run --script <skill-dir>/scripts/cli.py https://example.com
  uv run --script <skill-dir>/scripts/cli.py https://example.com --extract --format md
  uv run --script <skill-dir>/scripts/cli.py slides https://youtu.be/VIDEO
  uv run --script <skill-dir>/scripts/cli.py doctor

Use `--` before an underlying argument that starts with `--` if your runner parses it.
"""


def status_line(ok: bool, name: str, detail: str = "") -> str:
    tag = "[ok]  " if ok else "[miss]"
    return f"{tag} {name:<24} {detail}".rstrip()


def check_bin(name: str) -> bool:
    path = shutil.which(name)
    print(status_line(path is not None, name, path or ""))
    return path is not None


def check_env(env: Mapping[str, str], name: str) -> bool:
    ok = bool(env.get(name))
    print(status_line(ok, name, "set" if ok else ""))
    return ok


def doctor() -> int:
    print("== binaries ==")
    has_bun = check_bin("bun")
    for name in OPTIONAL_BINS:
        check_bin(name)

    print("\n== key env vars ==")
    for name in KEY_ENV_VARS:
        check_env(os.environ, name)

    config_path = Path.home() / ".summarize" / "config.json"
    print("\n== config ==")
    print(status_line(config_path.is_file(), str(config_path)))

    print("\n== summarize smoke ==")
    if not has_bun:
        print("skip: bun missing; install Bun to run summarize", file=sys.stderr)
        return 0

    completed = subprocess.run(
        ["bun", "x", PACKAGE, "--version"],
        shell=False,
    )
    return completed.returncode


def missing_bun() -> int:
    print("error: required executable not found: bun", file=sys.stderr)
    print(f"Install Bun or run on a host where `bun x {PACKAGE} ...` works.", file=sys.stderr)
    return 127


def run(argv: Sequence[str]) -> int:
    if argv and argv[0] == "--":
        argv = argv[1:]

    if not argv or argv[0] in {"-h", "--help"}:
        print(HELP)
        return 0

    if argv[0] == "doctor":
        return doctor()

    if shutil.which("bun") is None:
        return missing_bun()

    completed = subprocess.run(["bun", "x", PACKAGE, *argv], shell=False)
    return completed.returncode


def main() -> int:
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
