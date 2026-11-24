"""Wrapper contract: pinned sources, companions, exit codes, and usage errors."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

CLI = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
CHILD_EXIT = 3
USAGE_ERROR = 2
MISSING_EXECUTABLE = 127

FAKE_UVX = """import json, os, sys
from pathlib import Path
Path(os.environ["FAKE_UVX_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
sys.exit(int(os.environ.get("FAKE_UVX_EXIT", "0")))
"""


def make_uvx(directory: Path) -> Path:
    """Install a fake `uvx` on `directory` that logs its arguments."""
    directory.mkdir()
    script = directory / "fake_uvx.py"
    _ = script.write_text(FAKE_UVX, encoding="utf-8")
    if sys.platform == "win32":
        launcher = directory / "uvx.cmd"
        _ = launcher.write_text(
            f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
        )
    else:
        launcher = directory / "uvx"
        _ = launcher.write_text(f"#!{sys.executable}\n{FAKE_UVX}", encoding="utf-8")
        launcher.chmod(0o755)
    return directory


def run_cli(
    path: Path, log: Path, *args: str, exit_code: int = 0
) -> subprocess.CompletedProcess[str]:
    """Run the wrapper with only `path` on PATH."""
    env = {
        "PATH": str(path),
        "FAKE_UVX_LOG": str(log),
        "FAKE_UVX_EXIT": str(exit_code),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def logged(log: Path) -> list[str]:
    """Return the argv the fake uvx received, without its own path."""
    raw: object = json.loads(log.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] - checked below
    assert isinstance(raw, list)
    items = cast("list[object]", raw)
    argv = [item for item in items if isinstance(item, str)]
    assert len(argv) == len(items)
    return argv


def test_crapper_runs_pinned_commit_and_keeps_exit_code(tmp_path: Path) -> None:
    """Arguments pass through and the child exit code survives."""
    log = tmp_path / "argv.json"
    completed = run_cli(
        make_uvx(tmp_path / "bin"),
        log,
        "crapper",
        "--threshold",
        "30",
        "src",
        exit_code=CHILD_EXIT,
    )
    assert completed.returncode == CHILD_EXIT, completed.stderr
    argv = logged(log)
    assert argv[:3] == ["--python", "3.14", "--from"]
    assert argv[3].startswith("git+https://github.com/unclebob/crapper@")
    assert len(argv[3].rsplit("@", 1)[1]) == 40  # noqa: PLR2004 - full sha
    assert argv[4:] == ["crapper", "--threshold", "30", "src"]


def test_mutator_brings_pinned_crapper(tmp_path: Path) -> None:
    """The mutator run needs crapper importable in the same environment."""
    log = tmp_path / "argv.json"
    completed = run_cli(make_uvx(tmp_path / "bin"), log, "mutator", "--scan", "a.py")
    assert completed.returncode == 0, completed.stderr
    argv = logged(log)
    assert argv[3].startswith("git+https://github.com/unclebob/mutator@")
    assert argv[4] == "--with"
    assert argv[5].startswith("git+https://github.com/unclebob/crapper@")
    assert argv[6:] == ["mutator", "--scan", "a.py"]


def test_unknown_tool_is_usage_error(tmp_path: Path) -> None:
    """An unknown tool never reaches uvx."""
    log = tmp_path / "argv.json"
    completed = run_cli(make_uvx(tmp_path / "bin"), log, "pylint")
    assert completed.returncode == USAGE_ERROR
    assert "unknown tool" in completed.stderr
    assert not log.exists()


def test_no_arguments_prints_usage_and_fails(tmp_path: Path) -> None:
    """A bare call shows usage and exits 2; --help exits 0."""
    log = tmp_path / "argv.json"
    path = make_uvx(tmp_path / "bin")
    bare = run_cli(path, log)
    assert bare.returncode == USAGE_ERROR
    assert "Tools: crapper, dryer, mutator" in bare.stdout
    assert run_cli(path, log, "--help").returncode == 0
    assert not log.exists()


def test_missing_uvx_is_127(tmp_path: Path) -> None:
    """Without uvx the wrapper names the missing executable."""
    (tmp_path / "empty").mkdir()
    completed = run_cli(tmp_path / "empty", tmp_path / "argv.json", "dryer")
    assert completed.returncode == MISSING_EXECUTABLE
    assert "uvx" in completed.stderr
