"""Exercise the public commands with disposable repositories and forbidden clients."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest
from autoreview.verification import (
    Report,  # noqa: TC002 - cast evaluates the type at runtime
)

CLI = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _ = git(root, "init", "-b", "main")
    _ = git(root, "config", "user.name", "Tester")
    _ = git(root, "config", "user.email", "tester@example.com")
    _ = (root / "app.py").write_text(
        "def divide(n):\n    return n / 2\n", encoding="utf-8"
    )
    _ = git(root, "add", ".")
    _ = git(root, "commit", "-m", "Initial")
    _ = git(root, "branch", "base")
    _ = git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    home = repo.parent / "home"
    home.mkdir(exist_ok=True)
    bin_dir = repo.parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    marker = repo.parent / "forbidden-called"
    for name in ("omp", "codex", "claude", "pi", "amp", "kimi"):
        stub = bin_dir / name
        _ = stub.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\nraise SystemExit(99)\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
    env = dict(os.environ)
    env.update(HOME=str(home), PATH=f"{bin_dir}{os.pathsep}{env['PATH']}")
    _ = (bin_dir / "sitecustomize.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "def guard(event, args):\n"
        "    if event == 'subprocess.Popen' and Path(args[0]).name != 'git':\n"
        "        raise RuntimeError('Only git subprocesses are permitted')\n"
        "sys.addaudithook(guard)\n",  # pyright: ignore[reportImplicitStringConcatenation]
        encoding="utf-8",
    )
    env["PYTHONPATH"] = str(bin_dir)
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert not marker.exists(), "A forbidden reviewer process ran"
    return result


@pytest.mark.parametrize("mode", ["local", "branch", "commit", "auto"])
def test_bundle_modes(repo: Path, mode: str) -> None:
    _ = (repo / "app.py").write_text(
        "def divide(n):\n    return n / 0\n", encoding="utf-8"
    )
    if mode in {"branch", "commit"}:
        _ = git(repo, "commit", "-am", "Bug")
        _ = (repo / "app.py").write_text("dirty_excluded\n", encoding="utf-8")
    result = cli(repo, "bundle", "--mode", mode, "--base", "base")
    assert result.returncode == 0, result.stderr
    assert "+    return n / 0" in result.stdout
    assert "dirty_excluded" not in result.stdout
    assert "Base:" in result.stdout
    assert "Head:" in result.stdout
    assert "app.py" in result.stdout
    assert "+1" in result.stdout


def test_default_untracked_redaction_and_empty(repo: Path) -> None:
    empty = cli(repo, "--mode", "local")
    assert empty.returncode == 0
    assert "Empty diff" in empty.stdout
    for name in (".env", "server.pem", "new.py"):
        _ = (repo / name).write_text(f"unique-{name}\n", encoding="utf-8")
    result = cli(repo, "--mode", "local")
    assert result.returncode == 0
    assert "+unique-new.py" in result.stdout
    assert "unique-.env" not in result.stdout
    assert "unique-server.pem" not in result.stdout
    assert ".env" in result.stdout
    assert "server.pem" in result.stdout


def test_branch_auto_clean_and_root(repo: Path) -> None:
    root = cli(repo, "bundle", "--mode", "commit")
    assert root.returncode == 0
    assert "+def divide(n):" in root.stdout
    _ = (repo / "app.py").write_text("committed\n", encoding="utf-8")
    _ = git(repo, "commit", "-am", "Change")
    result = cli(repo, "--mode", "auto")
    assert result.returncode == 0
    assert "Target: branch" in result.stdout
    assert "+committed" in result.stdout


def test_local_index_only(repo: Path) -> None:
    _ = (repo / "app.py").write_text("index_bug\n", encoding="utf-8")
    _ = git(repo, "add", "app.py")
    _ = (repo / "app.py").write_text(
        "def divide(n):\n    return n / 2\n", encoding="utf-8"
    )
    result = cli(repo, "--mode", "local")
    assert result.returncode == 0
    assert "+index_bug" in result.stdout
    assert "INDEX" in result.stdout
    assert "WORKTREE" in result.stdout


def test_verify_index_only(repo: Path) -> None:
    _ = (repo / "app.py").write_text(
        "def divide(n):\n    return n / 0\n", encoding="utf-8"
    )
    _ = git(repo, "add", "app.py")
    _ = (repo / "app.py").write_text("fixed\n", encoding="utf-8")
    path = report(repo, state="INDEX")
    result = cli(
        repo,
        "verify",
        "--mode",
        "local",
        "--findings",
        str(path),
        "--max-priority",
        "P1",
    )
    assert result.returncode == 0, result.stderr
    assert "Zero divisor" in result.stdout
    path = report(repo, state="WORKTREE")
    invalid = cli(repo, "verify", "--mode", "local", "--findings", str(path))
    assert invalid.returncode == 1
    assert "finding 0" in invalid.stderr


def test_large_bundle_output(repo: Path) -> None:
    payload = "long_line_" * 100 + "\n"
    _ = (repo / "large.txt").write_text(payload * 500, encoding="utf-8")
    output = repo.parent / "bundle.txt"
    result = cli(repo, "bundle", "--mode", "local", "--output", str(output))
    assert result.returncode == 0
    assert len(result.stdout) < 12000
    assert str(output) in result.stdout
    assert output.read_text(encoding="utf-8").count("+" + payload) == 500
    automatic = cli(repo, "bundle", "--mode", "local")
    assert automatic.returncode == 0
    assert len(automatic.stdout) < 12000
    path = Path(automatic.stdout.split("Full bundle: ")[1].strip())
    assert path.read_text(encoding="utf-8").count("+" + payload) == 500


def report(repo: Path, **location: object) -> Path:
    finding = {
        "title": "Zero divisor",
        "body": "Every call raises ZeroDivisionError.",
        "priority": "P1",
        "confidence": 1.0,
        "category": "bug",
        "code_location": {
            "file_path": "app.py",
            "line": 2,
            "excerpt": "    return n / 0",
            **location,
        },
    }
    path = repo.parent / "findings.json"
    _ = path.write_text(
        json.dumps(
            {
                "summary": "Division fails",
                "overall_correctness": "patch is incorrect",
                "findings": [finding],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "location",
    [
        {},
        {"line": 99},
        {"file_path": "missing.py"},
        {"excerpt": "    return n / 9"},
        {"file_path": "../findings.json"},
    ],
)
def test_verify_locations(repo: Path, location: dict[str, object]) -> None:
    _ = (repo / "app.py").write_text(
        "def divide(n):\n    return n / 0\n", encoding="utf-8"
    )
    path = report(repo, **location)
    result = cli(
        repo,
        "verify",
        "--mode",
        "local",
        "--findings",
        str(path),
        "--max-priority",
        "P3",
    )
    assert result.returncode == (1 if location else 0), result.stderr
    if location:
        assert "finding 0" in result.stderr
    else:
        assert "Zero divisor" in result.stdout


def test_verify_snapshot_and_filter(repo: Path) -> None:
    _ = (repo / "app.py").write_text(
        "def divide(n):\n    return n / 0\n", encoding="utf-8"
    )
    _ = git(repo, "commit", "-am", "Bug")
    sha = git(repo, "rev-parse", "HEAD")
    _ = (repo / "app.py").write_text("working_tree_fixed\n", encoding="utf-8")
    path = report(repo)
    valid = cli(
        repo,
        "verify",
        "--mode",
        "commit",
        "--commit",
        sha,
        "--findings",
        str(path),
        "--max-priority",
        "P1",
    )
    assert valid.returncode == 0
    assert "Zero divisor" in valid.stdout
    filtered = cli(
        repo, "verify", "--mode", "commit", "--commit", sha, "--findings", str(path)
    )
    assert filtered.returncode == 0
    assert json.loads(filtered.stdout)["findings"] == []
    assert "Filtered: 1" in filtered.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("priority", "P4"),
        ("confidence", 1.1),
        ("confidence", True),
        ("category", "style"),
        ("title", ""),
        ("body", 3),
    ],
)
def test_verify_schema(repo: Path, field: str, value: object) -> None:
    _ = (repo / "app.py").write_text(
        "def divide(n):\n    return n / 0\n", encoding="utf-8"
    )
    path = report(repo)
    data = cast("Report", json.loads(path.read_text(encoding="utf-8")))
    data["findings"][0][field] = value
    _ = path.write_text(json.dumps(data), encoding="utf-8")
    result = cli(repo, "verify", "--mode", "local", "--findings", str(path))
    assert result.returncode == 1
    assert "finding 0" in result.stderr
