# Copyright (c) 2026 anntnzrb
"""Check compiled inventory comparison using recorded Nextest JSON, without Rust."""

import json
import os
import runpy
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "assets/governance-check.py"))
PARSE = cast("Callable[[str], dict[str, bool]]", MODULE["nextest_inventory"])
DOCS = cast("Callable[[str], dict[str, bool]]", MODULE["doctest_inventory"])
COMPARE = cast(
    "Callable[[dict[str, bool], dict[str, bool], set[str]], list[str]]",
    MODULE["compare_inventories"],
)


@pytest.fixture
def inventory_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide executable Cargo and rustc doubles without a Rust toolchain."""
    scripts = {
        "cargo": ("import json, os\nprint(json.dumps(dict(os.environ)))\n"),
        "rustc": (
            "import json, os, pathlib, sys\n"
            "_ = pathlib.Path(os.environ['RUSTC_ARGV_FILE']).write_text(\n"
            "    json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        ),
    }
    for name, body in scripts.items():
        executable = tmp_path / name
        _ = executable.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        executable.chmod(0o700)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("RUSTC_WORKSPACE_WRAPPER", raising=False)
    monkeypatch.setenv("RUSTFLAGS", "--cfg repository_tests")
    monkeypatch.setenv("CARGO_ENCODED_RUSTFLAGS", "--cfg\x1frepository_tests")
    return tmp_path


def test_inventory_build_uses_workspace_wrapper(inventory_tools: Path) -> None:
    """Inventory builds cap workspace lints without replacing Rust flags."""
    output = cast("Callable[..., str]", MODULE["command_output"])
    target = inventory_tools / "target"
    target.mkdir()
    environment = cast(
        "dict[str, str]",
        json.loads(output(["cargo"], inventory_tools, target=str(target))),
    )
    wrapper = Path(environment["RUSTC_WORKSPACE_WRAPPER"])
    assert wrapper == target / "cap-lints-rustc"
    assert wrapper.is_file()
    assert stat.S_IMODE(wrapper.stat().st_mode) == stat.S_IRWXU
    assert environment["CARGO_TARGET_DIR"] == str(target)
    for name in ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS"):
        assert environment.get(name) == os.environ.get(name)


def test_inventory_wrapper_preserves_rustc_arguments(
    inventory_tools: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The executable forwards rustc arguments in order and caps lints last."""
    output = cast("Callable[..., str]", MODULE["command_output"])
    target = inventory_tools / "target"
    target.mkdir()
    environment = cast(
        "dict[str, str]",
        json.loads(output(["cargo"], inventory_tools, target=str(target))),
    )
    arguments = inventory_tools / "rustc-arguments.json"
    monkeypatch.setenv("RUSTC_ARGV_FILE", str(arguments))
    _ = subprocess.run(
        [
            environment["RUSTC_WORKSPACE_WRAPPER"],
            str(inventory_tools / "rustc"),
            "--crate-name",
            "fixture",
            "--cfg",
            'feature="with spaces"',
            "--cap-lints=deny",
        ],
        check=True,
    )
    assert json.loads(arguments.read_text(encoding="utf-8")) == [
        "--crate-name",
        "fixture",
        "--cfg",
        'feature="with spaces"',
        "--cap-lints=deny",
        "--cap-lints=warn",
    ]


def test_non_inventory_command_has_no_workspace_wrapper(inventory_tools: Path) -> None:
    """Metadata and doctest execution do not acquire the inventory lint cap."""
    output = cast("Callable[..., str]", MODULE["command_output"])
    environment = cast("dict[str, str]", json.loads(output(["cargo"], inventory_tools)))
    assert "RUSTC_WORKSPACE_WRAPPER" not in environment
    assert environment["CARGO_TERM_COLOR"] == "never"


def inventory() -> dict[str, bool]:
    """Read real Nextest 0.9.136 output recorded on Rust 1.99.1."""
    return PARSE(
        (ROOT / "tests/fixtures/inventory/nextest-base.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.parametrize(
    "cause",
    ["rename", "ancestor cfg", "lib test=false", "autotests=false", "macro ignore"],
)
def test_missing_or_ignored_compiled_test(cause: str) -> None:
    """Every source/discovery mechanism is checked by its compiled inventory effect."""
    before = inventory()
    after = dict(before)
    identity = next(iter(before))
    if cause == "macro ignore":
        after[identity] = True
    else:
        del after[identity]
    errors = COMPARE(before, after, set())
    assert errors
    assert identity in errors[0]
    assert "human must approve" in errors[0]


def test_new_ordinary_test_is_allowed() -> None:
    """Adding a compiled test does not require a human exception."""
    before = inventory()
    after = {**before, "nextest:package:binary:new_test": False}
    assert COMPARE(before, after, set()) == []


def test_exact_trusted_approval() -> None:
    """Only an exact baseline identity can authorize its disappearance."""
    before = inventory()
    identity = next(iter(before))
    after = {key: value for key, value in before.items() if key != identity}
    assert COMPARE(before, after, {identity}) == []
    assert COMPARE(before, after, {"*"})


def test_recorded_paths_are_not_test_identities() -> None:
    """Build paths and package version IDs do not affect inventory identity."""
    text = (ROOT / "tests/fixtures/inventory/nextest-base.json").read_text(
        encoding="utf-8"
    )
    assert PARSE(text) == PARSE(
        text.replace("target", "other-build").replace("0.0.0", "0.1.0")
    )


def test_doctest_line_drift_and_removal() -> None:
    """Line-number shifts preserve identities while removed doctests fail."""
    before = DOCS("   Doc-tests library\nsrc/lib.rs - item (line 6): test\n")
    after = DOCS("   Doc-tests library\nsrc/lib.rs - item (line 16): test\n")
    assert COMPARE(before, after, set()) == []
    assert COMPARE(before, {}, set())


def test_invalid_inventory_fails_closed() -> None:
    """Malformed inventory output never becomes an empty successful comparison."""
    with pytest.raises((KeyError, TypeError, ValueError)):
        _ = PARSE(json.dumps({"rust-suites": {"binary": {"testcases": {}}}}))


def test_every_resolved_member_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cargo-resolved members are checked even when their manifests were unchanged."""
    member = tmp_path / "previously-nonmember.toml"
    _ = member.write_text('[package]\nname = "b"\n', encoding="utf-8")

    def resolver(_root: Path, _base: str = "HEAD") -> list[str]:
        return [str(member)]

    checker = cast("Callable[[Path], list[str]]", MODULE["member_findings"])
    monkeypatch.setitem(checker.__globals__, "workspace_members", resolver)
    assert "must inherit workspace lints" in checker(tmp_path)[0]
    _ = member.write_text(
        '[package]\nname = "b"\n[lints]\nworkspace = true\n', encoding="utf-8"
    )
    assert checker(tmp_path) == []


def test_mixed_doctest_comment_shift() -> None:
    """Lexically reordered line 7/10 listings preserve the mixed-state multiset."""
    parser = cast("Callable[[str, str], dict[str, bool]]", MODULE["doctest_inventory"])
    before = parser(
        """Doc-tests example
src/lib.rs - documented (line 6): test
src/lib.rs - documented (line 9): test
""",
        "Doc-tests example\nsrc/lib.rs - documented (line 6): test\n",
    )
    after = parser(
        """Doc-tests example
src/lib.rs - documented (line 10): test
src/lib.rs - documented (line 7): test
""",
        "Doc-tests example\nsrc/lib.rs - documented (line 7): test\n",
    )
    assert COMPARE(before, after, set()) == []
    assert COMPARE(before, dict.fromkeys(after, True), set())
    assert COMPARE(before, {}, set())


def test_binary_only_inventory_skips_doctests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolved binary targets have an empty doctest inventory without rustdoc calls."""
    collect = cast(
        "Callable[[Path, str], dict[str, bool]]", MODULE["collect_with_target"]
    )
    commands: list[list[str]] = []

    def output(
        command: list[str],
        _root: Path,
        *,
        target: str | None = None,
        combined: bool = False,
    ) -> str:
        del target, combined
        commands.append(command)
        assert "--doc" not in command
        if "metadata" in command:
            return json.dumps(
                {
                    "workspace_members": ["binary"],
                    "packages": [
                        {
                            "id": "binary",
                            "name": "binary",
                            "targets": [{"kind": ["bin"]}],
                        }
                    ],
                }
            )
        return '{"rust-suites": {}}'

    monkeypatch.setitem(collect.__globals__, "command_output", output)
    assert collect(tmp_path, str(tmp_path)) == {}
    assert any("metadata" in command for command in commands)


@pytest.mark.parametrize(
    ("manifest", "crates", "expected"),
    [
        (None, [], False),
        ('[workspace]\nresolver = "3"\n', [], False),
        ('[workspace]\nmembers = ["crates/*"]\n', [], False),
        ('[workspace]\nmembers = ["crates/*"]\n', ["crates/core/Cargo.toml"], True),
        (
            '[workspace]\nmembers = ["crates/[core]"]\n',
            ["crates/[core]/Cargo.toml"],
            True,
        ),
        (None, ["rust/crates/core/Cargo.toml"], True),
        ('[package]\nname = "root"\n', [], True),
        (
            '[project]\nname = "example"\nversion = "0.1.0"\nedition = "2021"\n',
            [],
            True,
        ),
        ("[workspace]\n[patch.crates-io]\n", [], True),
        (
            '[workspace]\nresolver = "3"\n[profile.release]\nlto = "thin"\n',
            [],
            False,
        ),
        ('[workspace]\n[workspace.lints.rust]\nunsafe_code = "deny"\n', [], False),
    ],
)
def test_trusted_base_package_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest: str | None,
    crates: list[str],
    *,
    expected: bool,
) -> None:
    """A base without any Cargo package has an empty inventory, not a failure."""
    has_packages = cast("Callable[[str, Path], bool]", MODULE["has_packages"])
    if manifest is not None:
        _ = (tmp_path / "Cargo.toml").write_text(manifest, encoding="utf-8")
    for entry in crates:
        path = tmp_path / entry
        path.parent.mkdir(parents=True)
        _ = path.write_text('[package]\nname = "core"\n', encoding="utf-8")
    commit_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert has_packages("HEAD", tmp_path) is expected


def commit_tree(root: Path) -> None:
    """Create a real committed baseline with deterministic local Git settings."""
    _ = (root / "README.md").write_text("Test baseline\n", encoding="utf-8")
    for arguments in (
        ["init", "--quiet"],
        ["config", "user.name", "Test"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "commit.gpgsign", "false"],
        ["add", "."],
        ["commit", "--quiet", "-m", "Baseline"],
    ):
        _ = subprocess.run(["git", *arguments], cwd=root, check=True)


def test_trusted_base_symlink_requires_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tracked symlink prevents proving that the baseline has no packages."""
    has_packages = cast("Callable[[str, Path], bool]", MODULE["has_packages"])
    _ = (tmp_path / "Cargo.toml").write_text("[workspace]\n", encoding="utf-8")
    (tmp_path / "link").symlink_to("README.md")
    commit_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert has_packages("HEAD", tmp_path) is True


def test_trusted_base_malformed_manifest_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed trusted TOML cannot silently disable inventory comparison."""
    has_packages = cast("Callable[[str, Path], bool]", MODULE["has_packages"])
    _ = (tmp_path / "Cargo.toml").write_text("[workspace", encoding="utf-8")
    commit_tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(tomllib.TOMLDecodeError):
        _ = has_packages("HEAD", tmp_path)


def test_trusted_base_checkout_manifest_requires_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout manifest altered by a smudge filter governs package detection."""
    has_packages = cast("Callable[[str, Path], bool]", MODULE["has_packages"])
    manifest = tmp_path / "Cargo.toml"
    _ = manifest.write_text("[workspace]\n", encoding="utf-8")
    commit_tree(tmp_path)
    _ = manifest.write_text('[package]\nname = "x"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert has_packages("HEAD", tmp_path) is True


@pytest.mark.parametrize("source", ["src/library.txt", "../outside.rs"])
def test_workspace_target_constraints_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    """Workspace targets must be Rust files owned by their manifest directory."""
    resolver = cast("Callable[[Path], list[str]]", MODULE["workspace_members"])

    def output(_command: list[str], _root: Path) -> str:
        return json.dumps(
            {
                "workspace_members": ["member"],
                "packages": [
                    {
                        "id": "member",
                        "manifest_path": str(tmp_path / "Cargo.toml"),
                        "targets": [
                            {"kind": ["lib"], "src_path": str(tmp_path / source)}
                        ],
                    }
                ],
            }
        )

    monkeypatch.setitem(resolver.__globals__, "command_output", output)
    with pytest.raises(ValueError, match="workspace target"):
        _ = resolver(tmp_path)


@pytest.mark.parametrize("approved", [False, True])
def test_metadata_custom_build_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, approved: bool
) -> None:
    """Metadata discovers nonstandard custom-build sources in a real Git history."""
    manifest = tmp_path / "Cargo.toml"
    _ = manifest.write_text(
        '[package]\nname = "member"\n[lints]\nworkspace = true\n', encoding="utf-8"
    )
    gate = tmp_path / ".gate"
    gate.mkdir()
    _ = (gate / "escape-hatch-paths").write_text(
        "custom.rs\n" if approved else "", encoding="utf-8"
    )
    source = tmp_path / "custom.rs"
    _ = source.write_text("fn main() {}\n", encoding="utf-8")
    commit_tree(tmp_path)
    _ = source.write_text('fn main() { println!("changed"); }\n', encoding="utf-8")
    checker = cast("Callable[[Path], list[str]]", MODULE["member_findings"])

    def output(_command: list[str], _root: Path) -> str:
        return json.dumps(
            {
                "workspace_members": ["member"],
                "packages": [
                    {
                        "id": "member",
                        "manifest_path": str(manifest),
                        "targets": [
                            {"kind": ["custom-build"], "src_path": str(source)}
                        ],
                    }
                ],
            }
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(checker.__globals__, "command_output", output)
    if approved:
        assert checker(tmp_path) == []
    else:
        with pytest.raises(ValueError, match="build script"):
            _ = checker(tmp_path)
