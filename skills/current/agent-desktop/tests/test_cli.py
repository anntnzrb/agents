"""Wrapper contract: pinned release, exit codes, and the unattended policy."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parents[1] / "scripts" / "cli.py"
CHILD_EXIT = 3
CONFIG_ERROR = 2
MISSING_EXECUTABLE = 127

FAKE_BUN = """import json, os, sys
from pathlib import Path
Path(os.environ["FAKE_BUN_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
sys.exit(int(os.environ.get("FAKE_BUN_EXIT", "0")))
"""


def make_skill(root: Path, pin: object) -> Path:
    """Lay out a skill copy whose UPSTREAM.json holds `pin`."""
    skill = root / "skill"
    (skill / "scripts").mkdir(parents=True)
    _ = shutil.copy(CLI, skill / "scripts" / "cli.py")
    _ = (skill / "UPSTREAM.json").write_text(json.dumps(pin), encoding="utf-8")
    return skill / "scripts" / "cli.py"


def make_bun(directory: Path) -> None:
    """Install a fake `bun` on `directory` that logs its arguments."""
    directory.mkdir()
    script = directory / "fake_bun.py"
    _ = script.write_text(FAKE_BUN, encoding="utf-8")
    if sys.platform == "win32":
        launcher = directory / "bun.cmd"
        _ = launcher.write_text(
            f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8"
        )
    else:
        launcher = directory / "bun"
        _ = launcher.write_text(f"#!{sys.executable}\n{FAKE_BUN}", encoding="utf-8")
        launcher.chmod(0o755)


def run_cli(
    cli: Path,
    path: Path,
    *args: str,
    exit_code: int = 0,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the wrapper with only `path` on PATH."""
    log = cli.parents[1] / "bun-argv.json"
    env = {
        "PATH": str(path),
        "FAKE_BUN_LOG": str(log),
        "FAKE_BUN_EXIT": str(exit_code),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    } | (extra_env or {})
    completed = subprocess.run(
        [sys.executable, str(cli), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return completed, log


def test_runs_pinned_release_and_preserves_exit_code(tmp_path: Path) -> None:
    """The npm version comes from `release`, and the child exit code survives."""
    cli = make_skill(tmp_path, {"release": "v9.8.7"})
    make_bun(tmp_path / "bin")
    completed, log = run_cli(
        cli, tmp_path / "bin", "snapshot", "--app", "Finder", "-i", exit_code=CHILD_EXIT
    )
    assert completed.returncode == CHILD_EXIT, completed.stderr
    assert json.loads(log.read_text(encoding="utf-8")) == [
        "x",
        "--trust",
        "agent-desktop@9.8.7",
        "snapshot",
        "--app",
        "Finder",
        "-i",
    ]


def test_leading_separator_is_dropped(tmp_path: Path) -> None:
    """A runner-protecting `--` does not reach agent-desktop."""
    cli = make_skill(tmp_path, {"release": "v1.0.0"})
    make_bun(tmp_path / "bin")
    completed, log = run_cli(cli, tmp_path / "bin", "--", "--version")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(log.read_text(encoding="utf-8")) == [
        "x",
        "--trust",
        "agent-desktop@1.0.0",
        "--version",
    ]


def test_missing_bun_is_127(tmp_path: Path) -> None:
    """Without bun the wrapper reports the missing executable."""
    cli = make_skill(tmp_path, {"release": "v1.0.0"})
    (tmp_path / "empty").mkdir()
    completed, log = run_cli(cli, tmp_path / "empty", "status")
    assert completed.returncode == MISSING_EXECUTABLE
    assert "bun" in completed.stderr
    assert not log.exists()


@pytest.mark.parametrize(
    "pin",
    [{"branch": "main"}, {"release": "v"}, ["v1.0.0"]],
    ids=["branch-pin", "empty-version", "not-an-object"],
)
def test_unusable_pin_is_a_config_error(tmp_path: Path, pin: object) -> None:
    """A pin without a usable release fails before anything runs."""
    cli = make_skill(tmp_path, pin)
    make_bun(tmp_path / "bin")
    completed, log = run_cli(cli, tmp_path / "bin", "status")
    assert completed.returncode == CONFIG_ERROR
    assert "release" in completed.stderr
    assert not log.exists()


BLOCKED = [
    pytest.param(["--headed", "click", "@s1:e1"], id="headed-global"),
    pytest.param(["click", "@s1:e1", "--headed"], id="headed-trailing"),
    pytest.param(["--headed=true", "click", "@s1:e1"], id="headed-equals"),
    pytest.param(["focus-window", "--window-id", "w-1"], id="focus-window"),
    pytest.param(["open-system-surface", "--surface", "dock"], id="system-surface"),
    pytest.param(["mcp"], id="mcp-bypass"),
    pytest.param(["launch", "TextEdit", "--activate"], id="launch-activate"),
    pytest.param(["permissions", "--guide"], id="permissions-guide"),
    pytest.param(["permissions", "--request"], id="permissions-request"),
    pytest.param(["press", "cmd+s"], id="press-unscoped"),
    pytest.param(["--session", "press", "press", "return"], id="value-named-press"),
    pytest.param(
        [
            "batch",
            json.dumps([{"command": "launch", "args": {"app": "X", "activate": True}}]),
        ],
        id="batch-launch-activate",
    ),
    pytest.param(
        ["batch", json.dumps([{"command": "press", "args": {"combo": "return"}}])],
        id="batch-press-unscoped",
    ),
    pytest.param(
        ["batch", json.dumps([{"command": "version"}, {"command": "focus-window"}])],
        id="batch-later-entry",
    ),
]

ALLOWED = [
    pytest.param(["snapshot", "--app", "Finder", "-i"], id="snapshot"),
    pytest.param(["launch", "TextEdit"], id="launch-background"),
    pytest.param(["permissions"], id="permissions-read"),
    pytest.param(["press", "7", "--app", "Calculator"], id="press-scoped-app"),
    pytest.param(["press", "return", "--window-id=w-1"], id="press-scoped-window"),
    pytest.param(["--session", "s1", "click", "@s1:e1"], id="session-value"),
    pytest.param(["type", "@s1:e1", "--", "--headed"], id="literal-after-separator"),
    pytest.param(
        [
            "batch",
            json.dumps([{"command": "press", "args": {"combo": "7", "app": "X"}}]),
        ],
        id="batch-press-scoped",
    ),
    pytest.param(
        [
            "batch",
            json.dumps(
                [{"command": "launch", "args": {"app": "X", "activate": False}}]
            ),
        ],
        id="batch-activate-false",
    ),
]


@pytest.mark.parametrize("args", BLOCKED)
def test_attended_requests_are_refused_before_running(
    tmp_path: Path, args: list[str]
) -> None:
    """Focus-taking or interrupting requests never reach agent-desktop."""
    cli = make_skill(tmp_path, {"release": "v1.0.0"})
    make_bun(tmp_path / "bin")
    completed, log = run_cli(cli, tmp_path / "bin", *args)
    assert completed.returncode == CONFIG_ERROR
    envelope = json.loads(completed.stdout)  # pyright: ignore[reportAny] - compared whole
    assert {
        "ok": envelope["ok"],
        "code": envelope["error"]["code"],
        "disposition": envelope["error"]["disposition"],
    } == {
        "ok": False,
        "code": "POLICY_DENIED",
        "disposition": {"delivery": "not_delivered", "retry": "safe"},
    }
    assert not log.exists()


@pytest.mark.parametrize("args", ALLOWED)
def test_headless_requests_run_unchanged(tmp_path: Path, args: list[str]) -> None:
    """Headless requests reach agent-desktop with their arguments intact."""
    cli = make_skill(tmp_path, {"release": "v1.0.0"})
    make_bun(tmp_path / "bin")
    completed, log = run_cli(cli, tmp_path / "bin", *args)
    assert completed.returncode == 0, completed.stdout
    assert json.loads(log.read_text(encoding="utf-8"))[3:] == args


def test_attended_opt_in_runs_blocked_request(tmp_path: Path) -> None:
    """The opt-in lets the user permit interruptions for one task."""
    cli = make_skill(tmp_path, {"release": "v1.0.0"})
    make_bun(tmp_path / "bin")
    args = ["--headed", "focus-window", "--window-id", "w-1"]
    completed, log = run_cli(
        cli, tmp_path / "bin", *args, extra_env={"AGENT_DESKTOP_ATTENDED": "1"}
    )
    assert completed.returncode == 0, completed.stdout
    assert json.loads(log.read_text(encoding="utf-8"))[3:] == args
