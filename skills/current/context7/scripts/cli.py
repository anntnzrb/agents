# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# ruff: noqa: CPY001

"""Load optional Context7 credentials and delegate commands to MCPorter."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

API_KEY_ENV = "CONTEXT7_API_KEY"
ENV_FILE_ENV = "CONTEXT7_ENV_FILE"
SKILL_NAME = "context7"
MIN_QUOTED_VALUE_LENGTH = 2
MISSING_EXECUTABLE_EXIT = 127
USAGE_ERROR_EXIT = 2
CONFIG_FLAG = "--config"
KEYLESS_NOTICE = f"{API_KEY_ENV} unset: anonymous access with lower rate limits"
AUTH_HEADER_RE = re.compile(
    r'(?m)^[ \t]*"Authorization"[ \t]*:[ \t]*"[^"]*CONTEXT7_API_KEY[^"]*"'
    r"[ \t]*,?[ \t]*\r?\n"
)


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


def stripped_config_text(config_path: Path) -> str | None:
    """Return config text without the Context7 auth header, or None if absent."""
    if not config_path.is_file():
        return None
    text = config_path.read_text(encoding="utf-8")
    stripped = AUTH_HEADER_RE.sub("", text)
    if stripped == text:
        return None
    return stripped


def default_config_path() -> Path:
    """Return the registry path supplied by the managed MCPorter wrapper."""
    return Path.home() / ".mcporter" / "mcporter.json"


def keyless_config_path(config_path: str) -> Path:
    """Materialize a header-stripped copy of the config for anonymous access."""
    stripped = stripped_config_text(Path(config_path))
    if stripped is None:
        return Path(config_path)
    fd, name = tempfile.mkstemp(suffix=".jsonc", prefix="context7-keyless-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(stripped)
    return Path(name)


def forward_args(args: list[str]) -> tuple[list[str], list[Path]]:
    """Rewrite the active config to a header-stripped copy for anonymous access."""
    if os.environ.get(API_KEY_ENV):
        return args, []
    result = list(args)
    cleanup: list[Path] = []
    has_config = False
    index = 0
    while index < len(result):
        argument = result[index]
        if argument == CONFIG_FLAG and index + 1 < len(result):
            has_config = True
            rewritten = keyless_config_path(result[index + 1])
            if rewritten != Path(result[index + 1]):
                cleanup.append(rewritten)
            result[index + 1] = str(rewritten)
            index += 2
            continue
        if argument.startswith(f"{CONFIG_FLAG}="):
            has_config = True
            rewritten = keyless_config_path(argument[len(CONFIG_FLAG) + 1 :])
            if rewritten != Path(argument[len(CONFIG_FLAG) + 1 :]):
                cleanup.append(rewritten)
            result[index] = f"{CONFIG_FLAG}={rewritten}"
        index += 1
    if has_config:
        return result, cleanup

    default_config = default_config_path()
    rewritten = keyless_config_path(str(default_config))
    if rewritten == default_config:
        return result, cleanup
    cleanup.append(rewritten)
    return [CONFIG_FLAG, str(rewritten), *result], cleanup


def run_mcporter(args: list[str]) -> int:
    """Run the managed MCPorter command and preserve its exit status."""
    try:
        return subprocess.run(  # noqa: S603
            ["mcporter", *args],  # noqa: S607
            check=False,
            env=os.environ.copy(),
        ).returncode
    except FileNotFoundError:
        sys.stderr.write("mcporter not found\n")
        return MISSING_EXECUTABLE_EXIT


def main(args: list[str] | None = None) -> int:
    """Load optional credentials and forward command-line arguments to MCPorter."""
    command_args = sys.argv[1:] if args is None else args
    if command_args == ["--help"]:
        sys.stdout.write("usage: context7 <mcporter arguments>\n")
        return 0
    load_env()
    cleanup: list[Path] = []
    if not os.environ.get(API_KEY_ENV):
        sys.stderr.write(f"{KEYLESS_NOTICE}\n")
        command_args, cleanup = forward_args(command_args)
    exit_code = run_mcporter(command_args)
    for path in cleanup:
        path.unlink(missing_ok=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
