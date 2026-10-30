# Copyright (c) 2026 anntnzrb
"""Check ordered gate behavior without Rust or external sockets."""

import os
import runpy
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

import pytest

CLI = Path(__file__).resolve().parents[1] / "scripts/cli.py"
MISSING_EXECUTABLE = 127
USAGE_ERROR = 2
CHECKER = CLI.parents[1] / "assets/governance-check.py"


def test_inventory_lint_debt_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive control compares an undocumented base to its documented fix."""
    module = runpy.run_path(str(CLI))
    verify = cast("Callable[[Path], None]", module["verify_inventory_controls"])
    fixture = CLI.parents[1] / "tests/fixtures/good"
    relative_source = Path("crates/fixture-core/src/lib.rs")
    original = (fixture / relative_source).read_text(encoding="utf-8")
    snapshots: list[tuple[str, str]] = []

    def fixture_repo(source: Path, repo: Path) -> str:
        _ = source.copy(repo)
        return "baseline"

    def run(command: list[str], repo: Path) -> str:
        if repo.name == "lint-debt":
            snapshots.append(
                (
                    " ".join(command),
                    (repo / relative_source).read_text(encoding="utf-8"),
                )
            )
        return ""

    def binary_only(_repo: Path) -> None:
        pass

    monkeypatch.setitem(verify.__globals__, "fixture_repo", fixture_repo)
    monkeypatch.setitem(verify.__globals__, "run", run)
    monkeypatch.setitem(verify.__globals__, "binary_only", binary_only)
    verify(tmp_path)
    assert [command for command, _ in snapshots] == [
        "git add .",
        "git commit --quiet -m Inventory control baseline",
        f"{sys.executable} {CHECKER} HEAD --inventory",
    ]
    capacity_doc = (
        "/// Reports whether a requested allocation fits within its "
        "available capacity.\n"
    )
    debt = original.replace(capacity_doc, "")
    assert snapshots[0][1] == debt
    assert snapshots[1][1] == debt
    assert snapshots[2][1] == original


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a git workspace with fake tool executables and real governance."""
    tools = tmp_path / "tools"
    tools.mkdir()
    fake = (
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "name = pathlib.Path(sys.argv[0]).name\n"
        "args = ' '.join(sys.argv[1:])\n"
        "if name == 'cargo' and sys.argv[1] == 'metadata':\n"
        "    import json\n"
        "    package = dict(id='fixture', name='fixture',\n"
        "        targets=[dict(kind=['lib'],\n"
        "            src_path=str(pathlib.Path.cwd() / 'src/lib.rs'))],\n"
        "        manifest_path=str(pathlib.Path.cwd() / 'Cargo.toml'))\n"
        "    nested = dict(id='nested', name='nested',\n"
        "        targets=[dict(kind=['bin'],\n"
        "            src_path=str(pathlib.Path.cwd() / 'crates/nested/src/lib.rs'))],\n"
        "        manifest_path=str(pathlib.Path.cwd() / 'crates/nested/Cargo.toml'))\n"
        "    packages = [package, nested]\n"
        "    if os.environ.get('FAIL_STEP') == 'unmapped': packages = []\n"
        "    metadata = dict(packages=packages,\n"
        "        workspace_members=[p['id'] for p in packages])\n"
        "    print(json.dumps(metadata))\n"
        "    sys.exit(0)\n"
        "if name == 'cargo' and sys.argv[1:3] == ['nextest', 'list']:\n"
        "    print('{\"rust-suites\": {}}')\n"
        "    sys.exit(0)\n"
        "if name == 'cargo' and '--list' in sys.argv:\n"
        "    sys.exit(0)\n"
        "with pathlib.Path(os.environ['GATE_LOG']).open('a') as log:\n"
        "    log.write(name + ' ' + args + '\\n')\n"
        "if (os.environ.get('FAIL_STEP') == 'unknown-lint'\n"
        "    and sys.argv[1] == 'clippy'):\n"
        "    print('warning: unknown lint: clippy::typo')\n"
        "if name == 'uv':\n"
        "    import subprocess\n"
        "    result = subprocess.run([sys.executable, *sys.argv[3:]], check=False)\n"
        "    sys.exit(result.returncode)\n"
        "if os.environ.get('FAIL_STEP') == sys.argv[1]:\n"
        "    print('deliberate tool failure')\n"
        "    sys.exit(3)\n"
        "if sys.argv[1:4] == ['+nightly', 'miri', 'test']:\n"
        "    pathlib.Path('miri-flags.txt').write_text(os.environ['MIRIFLAGS'])\n"
        "    cases = os.environ['PROPTEST_CASES']\n"
        "    pathlib.Path('proptest-cases.txt').write_text(cases)\n"
        "if sys.argv[1] == 'doc':\n"
        "    assert '-D warnings' in os.environ['RUSTDOCFLAGS']\n"
        "if name == 'cargo':\n"
        "    actual_target = os.environ['CARGO_TARGET_DIR']\n"
        "    assert actual_target == os.environ['GATE_PARENT_TARGET']\n"
    )
    for name in ("cargo", "uv"):
        file = tools / name
        _ = file.write_text(fake, encoding="utf-8")
        file.chmod(0o755)
    _ = (tmp_path / ".gitignore").write_text(
        "commands.log\nmiri-flags.txt\nproptest-cases.txt\n",
        encoding="utf-8",
    )
    gate = tmp_path / ".gate"
    gate.mkdir()
    _ = CHECKER.copy(gate / "governance-check.py")
    _ = (gate / "escape-hatch-paths").write_text(
        "src/*\ncrates/nested/src/*\n", encoding="utf-8"
    )
    _ = (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "fixture"\n[lints]\nworkspace = true\n', encoding="utf-8"
    )
    nested = tmp_path / "crates/nested"
    nested.mkdir(parents=True)
    _ = (nested / "Cargo.toml").write_text(
        '[package]\nname = "nested"\n[lints]\nworkspace = true\n', encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    _ = (tmp_path / "src/lib.rs").write_text("// original\n", encoding="utf-8")
    for args in (
        ("init", "--quiet"),
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@example.invalid"),
        ("config", "commit.gpgsign", "false"),
        ("add", "."),
        ("commit", "--quiet", "-m", "baseline"),
    ):
        _ = subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True
        )
    return tmp_path


def invoke(workspace: Path, failure: str = "") -> subprocess.CompletedProcess[str]:
    """Invoke the real CLI with deterministic external tool doubles."""
    target = os.environ.get("CARGO_TARGET_DIR", str(workspace / "real-target"))
    return subprocess.run(
        [sys.executable, str(CLI), "gate", "--path", str(workspace), "--base", "HEAD"],
        env={
            **os.environ,
            "PATH": f"{workspace / 'tools'}{os.pathsep}{os.environ['PATH']}",
            "GATE_LOG": str(workspace / "commands.log"),
            "FAIL_STEP": failure,
            "CARGO_TARGET_DIR": target,
            "GATE_PARENT_TARGET": target,
        },
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_full_gate_order(workspace: Path) -> None:
    """Every gate runs in order, with a diff file and documentation warning policy."""
    result = invoke(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    commands = (workspace / "commands.log").read_text(encoding="utf-8").splitlines()
    assert [line.split()[1] for line in commands] == [
        "fmt",
        "clippy",
        "nextest",
        "test",
        "doc",
        "deny",
        "machete",
        "run",
    ]
    assert "test --doc --all-features --locked --package fixture" in commands[3]
    assert "[9/9] Miri: no changes" in result.stdout


@pytest.mark.parametrize(
    ("failure", "name", "count"),
    [
        ("fmt", "format", 1),
        ("clippy", "clippy", 2),
        ("machete", "unused dependencies", 7),
    ],
)
def test_stop_on_failure(workspace: Path, failure: str, name: str, count: int) -> None:
    """Failures identify the step and prevent all subsequent gates."""
    result = invoke(workspace, failure)
    assert result.returncode == 1
    assert f"{name} failed" in result.stderr
    assert "deliberate tool failure" in result.stderr
    assert (
        len((workspace / "commands.log").read_text(encoding="utf-8").splitlines())
        == count
    )


def test_miri_for_unsafe_diff(workspace: Path) -> None:
    """Changes exercise packages with trusted escape-hatch files."""
    _ = (workspace / "src/lib.rs").write_text(
        "// unsafe adapter invariant\n", encoding="utf-8"
    )
    result = invoke(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        (workspace / "commands.log")
        .read_text(encoding="utf-8")
        .endswith("cargo +nightly miri test --all-features -p fixture\n")
    )


def test_missing_cargo(workspace: Path) -> None:
    """Missing executables use the repository's 127 convention."""
    # Executable lookup skips ENOENT entries, so a host cargo must be off PATH.
    (workspace / "tools/cargo").unlink()
    result = subprocess.run(
        [sys.executable, str(CLI), "gate", "--path", str(workspace), "--base", "HEAD"],
        env={**os.environ, "PATH": str(workspace / "tools")},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == MISSING_EXECUTABLE
    assert "missing executable" in result.stderr


def test_usage() -> None:
    """Help succeeds and an unknown subcommand is a usage error."""
    for argument, expected in (("--help", 0), ("unknown", 2)):
        result = subprocess.run(
            [sys.executable, str(CLI), argument], check=False, capture_output=True
        )
        assert result.returncode == expected


def test_unknown_lint_fails_closed(workspace: Path) -> None:
    """An unknown lint warning cannot masquerade as a passing Clippy gate."""
    result = invoke(workspace, "unknown-lint")
    assert result.returncode == 1
    assert "clippy failed:" in result.stderr
    assert "unknown-lint diagnostic" in result.stderr
    commands = (workspace / "commands.log").read_text(encoding="utf-8").splitlines()
    assert [line.split()[1] for line in commands] == ["fmt", "clippy"]


@pytest.mark.parametrize("name", ["missing", "plain-file"])
def test_invalid_workspace_path(tmp_path: Path, name: str) -> None:
    """Missing directories and ordinary files are usage errors, not missing tools."""
    path = tmp_path / name
    if name == "plain-file":
        _ = path.write_text("not a directory\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(CLI), "gate", "--path", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == USAGE_ERROR
    assert "usage:" in result.stderr
    assert "existing directory" in result.stderr


def test_untracked_rust_reaches_miri(workspace: Path) -> None:
    """Untracked Rust reaches the Miri decision without changing the index."""
    before = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=workspace,
        check=True,
        capture_output=True,
    ).stdout
    _ = (workspace / "src/new.rs").write_text(
        "// unsafe untracked adapter\n", encoding="utf-8"
    )
    result = invoke(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[9/9] Miri\n" in result.stdout
    after = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=workspace,
        check=True,
        capture_output=True,
    ).stdout
    assert after == before


def test_binary_attributes_cannot_hide_miri_input(workspace: Path) -> None:
    """A trusted binary attribute cannot suppress the gate's textual Rust patch."""
    _ = (workspace / ".gitattributes").write_text("*.rs -diff\n", encoding="utf-8")
    _ = subprocess.run(["git", "add", ".gitattributes"], cwd=workspace, check=True)
    _ = subprocess.run(
        ["git", "commit", "--quiet", "-m", "trusted binary attributes"],
        cwd=workspace,
        check=True,
    )
    _ = (workspace / "src/lib.rs").write_text(
        "// unsafe adapter invariant\n", encoding="utf-8"
    )
    result = invoke(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[9/9] Miri\n" in result.stdout


def test_non_rust_changes_trigger_approved_miri_packages(workspace: Path) -> None:
    """Changes to notes exercise approved packages without unsafe token edits."""
    _ = (workspace / ".gitignore").write_text("ignored.rs\n", encoding="utf-8")
    _ = subprocess.run(["git", "add", ".gitignore"], cwd=workspace, check=True)
    _ = subprocess.run(
        ["git", "commit", "--quiet", "-m", "ignore scratch source"],
        cwd=workspace,
        check=True,
    )
    _ = (workspace / "notes.txt").write_text("unsafe notes\n", encoding="utf-8")
    _ = (workspace / "ignored.rs").write_text(
        "unsafe ignored source\n", encoding="utf-8"
    )
    result = invoke(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[9/9] Miri\n" in result.stdout


@pytest.mark.parametrize("staged", [False, True])
def test_binary_image_does_not_enter_rust_patch(
    workspace: Path, *, staged: bool
) -> None:
    """Ordinary binary resources pass without UTF-8 decoding or Rust mutation input."""
    _ = (workspace / "image.png").write_bytes(bytes.fromhex("89504e470d0a1a0a00ff"))
    if staged:
        _ = subprocess.run(["git", "add", "image.png"], cwd=workspace, check=True)
    result = invoke(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[9/9] Miri\n" in result.stdout


def test_invalid_utf8_rust_fails_cleanly(workspace: Path) -> None:
    """Undecodable governed content fails closed without a Python traceback."""
    _ = (workspace / "src/new.rs").write_bytes(b"\xff")
    result = invoke(workspace)
    assert result.returncode == 1
    assert "invalid governed content" in result.stderr
    assert "Traceback" not in result.stderr


def test_inventory_failure_removes_baseline_worktree(workspace: Path) -> None:
    """A failed trusted build still removes the detached inventory worktree."""
    cargo = workspace / "tools/cargo"
    condition = "if name == 'cargo' and sys.argv[1:3] == ['nextest', 'list']:\n"
    text = cargo.read_text(encoding="utf-8").replace(
        condition, f"{condition}    sys.exit(7)\n"
    )
    _ = cargo.write_text(text, encoding="utf-8")
    result = invoke(workspace)
    assert result.returncode == 1
    assert "inventory command failed" in result.stderr
    worktrees = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert worktrees.count("worktree ") == 1


@pytest.mark.parametrize("existing_flags", ["", "-Zmiri-seed=42"])
def test_miri_scopes_unsafe_package(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, existing_flags: str
) -> None:
    """All containing approved packages run, preserving caller Miri flags first."""
    monkeypatch.setenv("MIRIFLAGS", existing_flags)
    source = workspace / "crates/nested/src/lib.rs"
    source.parent.mkdir(parents=True, exist_ok=True)
    _ = source.write_text("// unsafe nested invariant\n", encoding="utf-8")
    _ = (workspace / "src/lib.rs").write_text("// safe change\n", encoding="utf-8")
    result = invoke(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    commands = (workspace / "commands.log").read_text(encoding="utf-8").splitlines()
    assert (
        commands[-1] == "cargo +nightly miri test --all-features -p fixture -p nested"
    )
    assert (workspace / "miri-flags.txt").read_text(encoding="utf-8") == (
        f"{existing_flags} -Zmiri-disable-isolation -Zmiri-strict-provenance".strip()
    )


def test_miri_unmapped_unsafe_fails_closed(workspace: Path) -> None:
    """Unsafe source without a workspace package cannot silently skip Miri."""
    _ = (workspace / "src/lib.rs").write_text("// unsafe invariant\n", encoding="utf-8")
    result = invoke(workspace, "unmapped")
    assert result.returncode == 1
    assert "Miri failed" in result.stderr
    assert "cannot map" in result.stderr
    assert "miri test" not in (workspace / "commands.log").read_text(encoding="utf-8")


def test_miri_packages_sorted_and_unique(workspace: Path) -> None:
    """Multiple unsafe files select each owning package exactly once in order."""
    nested = workspace / "crates/nested/src"
    nested.mkdir(parents=True)
    for source in (workspace / "src/lib.rs", nested / "lib.rs", nested / "ffi.rs"):
        _ = source.write_text("// unsafe invariant\n", encoding="utf-8")
    result = invoke(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    commands = (workspace / "commands.log").read_text(encoding="utf-8").splitlines()
    assert (
        commands[-1] == "cargo +nightly miri test --all-features -p fixture -p nested"
    )


@pytest.mark.parametrize("existing_cases", [None, "5", ""])
def test_miri_body_only_edit_and_property_budget(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, existing_cases: str | None
) -> None:
    """An unchanged unsafe token cannot hide a body edit from Miri."""
    if existing_cases is None:
        monkeypatch.delenv("PROPTEST_CASES", raising=False)
    else:
        monkeypatch.setenv("PROPTEST_CASES", existing_cases)
    file = workspace / "src/lib.rs"
    original = "pub fn read(x: &[u8]) -> u8 { unsafe {\n*x.get_unchecked(0)\n} }\n"
    _ = file.write_text(original, encoding="utf-8")
    _ = subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    _ = subprocess.run(
        ["git", "commit", "--quiet", "-m", "trusted unsafe block"],
        cwd=workspace,
        check=True,
    )
    _ = file.write_text(
        original.replace("unchecked(0)", "unchecked(1)"), encoding="utf-8"
    )
    result = invoke(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[9/9] Miri\n" in result.stdout
    assert (workspace / "proptest-cases.txt").read_text(encoding="utf-8") == (
        "16" if existing_cases is None else existing_cases
    )


def test_miri_empty_trusted_selection(workspace: Path) -> None:
    """A workspace without approved files explicitly skips Miri."""
    _ = (workspace / ".gate/escape-hatch-paths").write_text(
        "unmatched/*\n", encoding="utf-8"
    )
    _ = subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    _ = subprocess.run(
        ["git", "commit", "--quiet", "-m", "no approved sources"],
        cwd=workspace,
        check=True,
    )
    _ = (workspace / "src/lib.rs").write_text("// ordinary change\n", encoding="utf-8")
    result = invoke(workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[9/9] Miri: no packages in escape-hatch paths" in result.stdout
    assert "miri test" not in (workspace / "commands.log").read_text(encoding="utf-8")


def test_miri_trusted_selection_ignores_proposed_allowlist(workspace: Path) -> None:
    """The current allowlist cannot remove trusted package selection."""
    module = runpy.run_path(str(CLI))
    select = cast("Callable[[Path, str], list[str]]", module["miri_packages"])
    monkey_environment = {
        **os.environ,
        "PATH": f"{workspace / 'tools'}{os.pathsep}{os.environ['PATH']}",
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "environ", monkey_environment)
        _ = (workspace / ".gate/escape-hatch-paths").write_text("", encoding="utf-8")
        assert select(workspace, "HEAD") == ["fixture"]


def test_miri_rejects_ambiguous_member_directories(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distinct members sharing the deepest directory fail closed."""
    module = runpy.run_path(str(CLI))
    select = cast("Callable[[Path, str], list[str]]", module["miri_packages"])
    monkeypatch.setenv("PATH", f"{workspace / 'tools'}{os.pathsep}{os.environ['PATH']}")
    cargo = workspace / "tools/cargo"
    _ = cargo.write_text(
        cargo.read_text(encoding="utf-8").replace(
            "packages = [package, nested]",
            "packages = [package, dict(package, id='duplicate', name='duplicate')]",
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="ambiguous"):
        _ = select(workspace, "HEAD")
