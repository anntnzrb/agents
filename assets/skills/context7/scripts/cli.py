# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# ruff: noqa: CPY001

"""Load Context7 credentials and delegate commands to MCPorter."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

API_KEY_ENV = "CONTEXT7_API_KEY"
ENV_FILE_ENV = "CONTEXT7_ENV_FILE"
SKILL_NAME = "context7"
MIN_QUOTED_VALUE_LENGTH = 2
MISSING_EXECUTABLE_EXIT = 127
USAGE_ERROR_EXIT = 2


def parse_env_file(path: Path) -> bool:
    """Load dotenv assignments from path when it exists."""
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text.removeprefix("export ").lstrip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (
            len(value) >= MIN_QUOTED_VALUE_LENGTH
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return True


def ancestor_env() -> Path | None:
    """Find a Context7 dotenv file beneath an ancestor skills directory."""
    here = Path.cwd().resolve()
    for directory in (here, *here.parents):
        candidate = directory / "skills" / SKILL_NAME / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env() -> None:
    """Load Context7 dotenv without overriding the current process."""
    if os.environ.get(API_KEY_ENV):
        return
    skill_dir = Path(__file__).resolve().parents[1]
    candidates: list[Path | None] = []
    if env_file := os.environ.get(ENV_FILE_ENV):
        candidates.append(Path(env_file).expanduser())
    candidates.append(skill_dir / ".env")
    if skills_dir := os.environ.get("SKILLS_DIR"):
        candidates.append(Path(skills_dir).expanduser() / SKILL_NAME / ".env")
    candidates.append(ancestor_env())
    for candidate in candidates:
        if candidate is not None and parse_env_file(candidate):
            return


def mcporter_command(args: list[str]) -> list[str] | None:
    """Build the native MCPorter command or its Nix fallback."""
    if executable := shutil.which("mcporter"):
        return [executable, *args]
    if executable := shutil.which("nix"):
        return [
            executable,
            "run",
            "github:numtide/llm-agents.nix#mcporter",
            "--",
            *args,
        ]
    return None


def run_mcporter(args: list[str]) -> int:
    """Run MCPorter with inherited credentials and preserve its exit status."""
    if (command := mcporter_command(args)) is None:
        sys.stderr.write("mcporter not found and nix fallback unavailable\n")
        return MISSING_EXECUTABLE_EXIT
    return subprocess.run(command, check=False, env=os.environ.copy()).returncode  # noqa: S603


def main(args: list[str] | None = None) -> int:
    """Load credentials and forward command-line arguments to MCPorter."""
    command_args = sys.argv[1:] if args is None else args
    if command_args == ["--help"]:
        sys.stdout.write("usage: context7 <mcporter arguments>\n")
        return 0
    load_env()
    if not os.environ.get(API_KEY_ENV):
        sys.stderr.write(
            f"{API_KEY_ENV} required "
            f"(export it, use this skill's .env, or set {ENV_FILE_ENV})\n",
        )
        return USAGE_ERROR_EXIT
    return run_mcporter(command_args)


if __name__ == "__main__":
    raise SystemExit(main())
