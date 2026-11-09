"""Public entrypoints run the way users run them, as executables in a fresh process."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import odooctl
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
ENTRYPOINTS = ("cli.py", "odooctl.py", "odoo_rpc.py", "xml_view_linter.py")


def user_path() -> str:
    """PATH without the test interpreter's bin dir, as in the user's own shell."""
    venv_bin = str(Path(sys.executable).parent)
    return os.pathsep.join(
        p for p in os.environ.get("PATH", "").split(os.pathsep) if p != venv_bin
    )


def run_script(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPTS / argv[0]), *argv[1:]],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env=os.environ | {"PATH": user_path(), "VIRTUAL_ENV": ""},
    )


@pytest.mark.skipif(shutil.which("uv") is None, reason="entrypoints run through uv")
@pytest.mark.parametrize("script", ENTRYPOINTS)
def test_executable_entrypoint_starts_under_its_declared_python(script: str) -> None:
    """The shebang resolves the PEP 723 interpreter and deps, not the system python3."""
    result = run_script(script, "--help")
    assert result.returncode == 0, result.stderr[-2000:]
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(shutil.which("uv") is None, reason="entrypoints run through uv")
def test_cli_dispatches_every_odooctl_command() -> None:
    """Every odooctl subcommand reaches odooctl through cli.py, including 'rpc' as a value."""
    for name in sorted(odooctl.command_names()):
        result = run_script("cli.py", name, "--help")
        assert result.returncode == 0, (name, result.stderr[-500:])
        assert f"odooctl {name}" in result.stdout, name
    shell = run_script("cli.py", "shell", "--file", "rpc")
    assert "RPC flags go with the rpc command" not in shell.stderr


def test_every_parser_command_has_a_handler() -> None:
    """A subcommand the parser accepts but main() cannot dispatch prints help and exits 1."""
    usage = odooctl.build_parser().format_usage()
    listed = re.search(r"\{([^}]+)\}", usage)
    assert listed is not None, usage
    assert frozenset(listed.group(1).split(",")) == odooctl.command_names()
