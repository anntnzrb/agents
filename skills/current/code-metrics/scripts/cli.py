# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Run a pinned crapper, dryer, or mutator through uvx."""

import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

OWNER = "unclebob"
PYTHON = "3.14"
# Tool name to upstream commit. Update by hand; see SKILL.md "Maintenance".
PINS = {
    "crapper": "c757ec79a6c15dc815238bbd9c2f4601eb54d3cc",
    "dryer": "66ff6d21a42c04afcad89c78a80066176d1294b0",
    "mutator": "0136cf555797f1c9552388c40207eb2f13af9535",
}
# mutator imports crapper for function names; install it into the same env.
COMPANIONS = {"mutator": ("crapper",)}
USAGE_ERROR = 2
MISSING_EXECUTABLE = 127

HELP = f"""code-metrics wrapper

Usage:
  uv run --script <skill-dir>/scripts/cli.py <tool> <tool-args>...

Tools: {", ".join(PINS)}

Delegates to:
  uvx --python {PYTHON} --from git+https://github.com/{OWNER}/<tool>@<sha> <tool> ...

mutator also gets crapper at its pinned commit. Use `<tool> --help` for the
tool's own options. The child exit code is preserved.
"""


def source(tool: str) -> str:
    """Return the pinned uv source for `tool`."""
    return f"git+https://github.com/{OWNER}/{tool}@{PINS[tool]}"


def command(uvx: str, tool: str, args: Sequence[str]) -> list[str]:
    """Build the uvx argument vector for `tool`."""
    argv = [uvx, "--python", PYTHON, "--from", source(tool)]
    for companion in COMPANIONS.get(tool, ()):
        argv += ["--with", source(companion)]
    return [*argv, tool, *args]


def run(argv: Sequence[str]) -> int:
    """Dispatch to the pinned tool and return its exit code."""
    if not argv or argv[0] in {"-h", "--help"}:
        print(HELP)
        return 0 if argv else USAGE_ERROR
    tool, *rest = argv
    if tool not in PINS:
        print(f"error: unknown tool {tool!r}; choose one of: {', '.join(PINS)}",
              file=sys.stderr)  # fmt: skip
        return USAGE_ERROR
    uvx = shutil.which("uvx")
    if uvx is None:
        print("error: required executable not found: uvx", file=sys.stderr)
        print("Install uv: https://docs.astral.sh/uv/", file=sys.stderr)
        return MISSING_EXECUTABLE
    return subprocess.run(command(uvx, tool, rest), shell=False, check=False).returncode


def main() -> int:
    """Run the wrapper with the process arguments."""
    return run(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
