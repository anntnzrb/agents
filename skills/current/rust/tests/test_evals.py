# Copyright (c) 2026 anntnzrb
"""Recreate evaluation repositories without Rust or network access."""

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TypedDict, cast

import pytest

SKILL = Path(__file__).resolve().parents[1]
CLI = SKILL / "scripts/cli.py"
USAGE_ERROR = 2


class Eval(TypedDict):
    """Evaluation fields inspected by the seed integrity check."""

    id: int
    prompt: str
    files: list[str]


class Suite(TypedDict):
    """Persisted evaluation suite."""

    skill_name: str
    evals: list[Eval]


def git(repo: Path, *args: str) -> str:
    """Read real repository state."""
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.mark.parametrize("task", ["async", "library", "ffi", "retrofit"])
def test_eval_setup(tmp_path: Path, task: str) -> None:
    """Each task gets the original history and byte-identical human gates."""
    dest = tmp_path / task
    result = subprocess.run(
        [sys.executable, str(CLI), "eval-setup", "--task", task, "--dest", str(dest)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert str(dest) in result.stdout
    assert (
        f"prompt id: {['async', 'library', 'ffi', 'retrofit'].index(task) + 1}"
        in result.stdout
    )
    assert git(dest, "branch", "--show-current") == "main"
    messages = ["Install human-owned gates"]
    if task == "retrofit":
        messages.append("Legacy tally")
    assert git(dest, "log", "--format=%s").splitlines() == messages
    assert git(dest, "status", "--porcelain") == ""
    assert git(dest, "log", "--format=%an <%ae>").splitlines() == [
        "eval <eval@example.invalid>"
    ] * len(messages)
    for name in ("clippy.toml", "rustfmt.toml", "deny.toml", "rust-toolchain.toml"):
        assert (dest / name).read_bytes() == (SKILL / "assets" / name).read_bytes()
    assert (dest / ".gate/governance-check.py").read_bytes() == (
        SKILL / "assets/governance-check.py"
    ).read_bytes()
    manifest = tomllib.loads((dest / "Cargo.toml").read_text(encoding="utf-8"))
    assert "clippy" in manifest["workspace"]["lints"]
    if task == "retrofit":
        assert manifest["package"]["name"] == "tally"
        assert manifest["lints"]["workspace"] is True
        seed = SKILL / "evals/files/retrofit"
        for source in seed.rglob("*"):
            if source.is_file():
                assert (
                    subprocess.run(
                        [
                            "git",
                            "show",
                            f"HEAD~1:{source.relative_to(seed).as_posix()}",
                        ],
                        cwd=dest,
                        check=True,
                        capture_output=True,
                    ).stdout
                    == source.read_bytes()
                )
    else:
        assert "package" not in manifest
        assert manifest["workspace"]["resolver"] == "3"
    if task == "ffi":
        assert (dest / ".gate/escape-hatch-paths").read_text(
            encoding="utf-8"
        ) == "crates/*-ffi/*\n"
        for name in ("adler32.c", "adler32.h"):
            assert (dest / "vendor" / name).read_bytes() == (
                SKILL / "evals/files/ffi/vendor" / name
            ).read_bytes()


def test_eval_setup_existing_directory(tmp_path: Path) -> None:
    """Existing destinations are usage errors and remain untouched."""
    marker = tmp_path / "keep"
    _ = marker.write_text("original", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "eval-setup",
            "--task",
            "async",
            "--dest",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == USAGE_ERROR
    assert "must not exist" in result.stderr
    assert list(tmp_path.iterdir()) == [marker]
    assert marker.read_text(encoding="utf-8") == "original"


def test_eval_suite() -> None:
    """Every prompt is portable and every referenced seed ships with the skill."""
    suite = cast(
        "Suite", json.loads((SKILL / "evals/evals.json").read_text(encoding="utf-8"))
    )
    assert suite["skill_name"] == "rust"
    ids = [evaluation["id"] for evaluation in suite["evals"]]
    assert sorted(ids) == [1, 2, 3, 4]
    for evaluation in suite["evals"]:
        assert "/tmp" not in evaluation["prompt"]  # noqa: S108 - reject machine paths
        assert "/home" not in evaluation["prompt"]
        for relative in evaluation["files"]:
            assert (SKILL / relative).is_file()
