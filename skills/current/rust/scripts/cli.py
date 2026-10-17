# Copyright (c) 2026 anntnzrb
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Run the Rust quality gate and verify its reference fixtures."""

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import cast


class Options(argparse.Namespace):
    """Typed arguments at the argparse boundary."""

    command: str = ""
    base: str = "origin/main"
    path: Path = Path.cwd()
    task: str = ""
    dest: Path = Path.cwd()


SKILL = Path(__file__).resolve().parents[1]
CORE = Path("crates/fixture-core")
COMMANDS = (
    ("format", ("cargo", "fmt", "--all", "--check")),
    (
        "clippy",
        (
            "cargo",
            "clippy",
            "--workspace",
            "--all-targets",
            "--all-features",
            "--locked",
            "--",
            "-D",
            "warnings",
        ),
    ),
    ("tests", ("cargo", "nextest", "run", "--workspace", "--all-features", "--locked")),
    (
        "doctests",
        (sys.executable, str(SKILL / "assets/governance-check.py"), "--doctests"),
    ),
    ("docs", ("cargo", "doc", "--no-deps", "--workspace", "--locked")),
    ("dependencies", ("cargo", "deny", "--locked", "check")),
    ("unused dependencies", ("cargo", "machete")),
)
EXPECTED = {
    "panic": "clippy::unwrap_used",
    "allow": "clippy::allow_attributes",
    "ignored test": "clippy::ignore_without_reason",
    "unsafe": "clippy::undocumented_unsafe_blocks",
    "ignored result": "clippy::let_underscore_must_use",
    "arithmetic": "clippy::arithmetic_side_effects",
    "wildcard match": "clippy::wildcard_enum_match_arm",
}


def run(
    command: list[str] | tuple[str, ...],
    path: Path,
    *,
    docs: bool = False,
    display: bool = True,
    miri: bool = False,
) -> str:
    """Run a checked command, retaining diagnostics for fixture assertions."""
    env = dict(os.environ)
    if tuple(command[:2]) == ("cargo", "mutants"):
        output = Path(command[command.index("--output") + 1])
        if os.name == "nt":
            raise RuntimeError("mutation mode requires a POSIX host")
        wrapper = output / "cap-lints-rustc"
        _ = wrapper.write_text(
            f"""#!{sys.executable}
import os
import sys
os.execvp(sys.argv[1], [sys.argv[1], *sys.argv[2:], "--cap-lints=warn"])
""",
            encoding="utf-8",
        )
        wrapper.chmod(0o700)
        env |= {
            "CARGO_TARGET_DIR": str(output / "mutants-target"),
            "RUSTC_WORKSPACE_WRAPPER": str(wrapper),
        }
    if docs:
        env["RUSTDOCFLAGS"] = f"{env.get('RUSTDOCFLAGS', '')} -D warnings".strip()
    if miri:
        _ = env.setdefault("PROPTEST_CASES", "16")
        env["MIRIFLAGS"] = (
            f"{env.get('MIRIFLAGS', '')} "
            "-Zmiri-disable-isolation -Zmiri-strict-provenance"
        ).strip()
    result = subprocess.run(
        command,
        cwd=path,
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    if display:
        print(result.stdout, end="", flush=True)
    if "unknown lint" in result.stdout:
        raise RuntimeError("tool emitted an unknown-lint diagnostic")
    return result.stdout


DIFF_FLAGS = (
    "--text",
    "--no-textconv",
    "--no-ext-diff",
    "--no-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
)


def workspace_diff(path: Path, base: str) -> tuple[str, bool]:
    """Diff explicit tracked and untracked paths without changing the index."""
    tracked = run(
        ["git", "diff", "--no-renames", "--name-only", "-z", base],
        path,
        display=False,
    )
    untracked = set(
        run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            path,
            display=False,
        ).split("\0")
    )
    names = (set(tracked.split("\0")) | untracked) - {""}
    patches: list[str] = []
    for name in sorted(names):
        governed = (
            name.endswith(".rs")
            or Path(name).name
            in {
                "Cargo.toml",
                "Cargo.lock",
                ".gitattributes",
                ".gitmodules",
                "deny.toml",
                "clippy.toml",
                ".clippy.toml",
                "rustfmt.toml",
                ".rustfmt.toml",
                "rust-toolchain",
                "rust-toolchain.toml",
            }
            or name.startswith((".gate/", ".github/", ".cargo/", ".config/"))
        )
        if not governed:
            continue
        command = ["git", "diff", *DIFF_FLAGS]
        command.extend(
            ["--no-index", "--", "/dev/null", name]
            if name in untracked
            else [base, "--", name]
        )
        result = subprocess.run(
            command,
            cwd=path,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode not in ((0, 1) if name in untracked else (0,)):
            raise subprocess.CalledProcessError(
                result.returncode, command, result.stdout, result.stderr
            )
        patches.append(result.stdout)
    return "".join(patches), bool(names)


def json_object(value: object) -> dict[str, object]:
    """Validate Cargo metadata objects at the process boundary."""
    if not isinstance(value, dict):
        raise TypeError("invalid cargo metadata object")
    return cast("dict[str, object]", value)


def miri_packages(path: Path, base: str) -> list[str]:
    """Select every workspace member containing a trusted escape-hatch path."""
    ancestor = run(["git", "merge-base", base, "HEAD"], path, display=False).strip()
    allowlist = ".gate/escape-hatch-paths"
    exists = run(
        ["git", "ls-tree", "--name-only", "-z", ancestor, "--", allowlist],
        path,
        display=False,
    )
    trusted = (
        run(["git", "show", f"{ancestor}:{allowlist}"], path, display=False)
        if exists
        else ""
    )
    patterns = [
        line.strip()
        for line in trusted.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    files = run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        path,
        display=False,
    ).split("\0")
    output = run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1", "--locked"],
        path,
        display=False,
    )
    metadata = json_object(cast("object", json.loads(output)))
    packages, members = metadata.get("packages"), metadata.get("workspace_members")
    if not isinstance(packages, list) or not isinstance(members, list):
        raise TypeError("invalid cargo metadata packages/members")
    member_ids = cast("list[object]", members)
    owners: list[tuple[Path, str]] = []
    for value in cast("list[object]", packages):
        package = json_object(value)
        if package.get("id") not in member_ids:
            continue
        manifest, name = package.get("manifest_path"), package.get("name")
        if not isinstance(manifest, str) or not isinstance(name, str) or not name:
            raise RuntimeError("invalid cargo metadata manifest/name")
        owners.append((Path(manifest).resolve().parent, name))
    selected: set[str] = set()
    for source in sorted(set(files) - {""}):
        if not any(fnmatch.fnmatchcase(source, pattern) for pattern in patterns):
            continue
        containing = [
            (directory, name)
            for directory, name in owners
            if (path / source).resolve().is_relative_to(directory)
        ]
        deepest = max((len(directory.parts) for directory, _ in containing), default=0)
        matches = {
            name for directory, name in containing if len(directory.parts) == deepest
        }
        if len(matches) > 1:
            raise RuntimeError(
                f"ambiguous workspace package for escape-hatch path: {source}"
            )
        if not matches:
            raise RuntimeError(
                f"cannot map escape-hatch path to workspace package: {source}"
            )
        selected.update(matches)
    return sorted(selected)


def gate(path: Path, base: str) -> int:
    """Run the ten ordered steps and stop at the first failed command."""
    step = "prepare diff"
    try:
        with tempfile.TemporaryDirectory(prefix="rust-gate-") as temporary:
            for number, (step, command) in enumerate(COMMANDS, 1):
                print(f"[{number}/10] {step}", flush=True)
                _ = run(command, path, docs=step == "docs")
            step = "mutation tests"
            diff, changed = workspace_diff(path, base)
            patch = Path(temporary) / "diff.patch"
            _ = patch.write_text(diff, encoding="utf-8")
            print(f"[8/10] {step}", flush=True)
            _ = run(
                [
                    "cargo",
                    "mutants",
                    "--in-diff",
                    str(patch),
                    "--test-tool",
                    "nextest",
                    "--output",
                    temporary,
                ],
                path,
            )
            step = "governance"
            print(f"[9/10] {step}", flush=True)
            # Execute the trusted base copy, never the branch's editable checker.
            checker = run(
                ["git", "show", f"{base}:.gate/governance-check.py"],
                path,
                display=False,
            )
            trusted = Path(temporary) / "governance-check.py"
            _ = trusted.write_text(checker, encoding="utf-8")
            _ = run(["uv", "run", "--script", str(trusted), base, "--inventory"], path)
            step = "Miri"
            packages = miri_packages(path, base) if changed else []
            if packages:
                print(f"[10/10] {step}", flush=True)
                command = ["cargo", "+nightly", "miri", "test", "--all-features"]
                for package in packages:
                    command.extend(["-p", package])
                _ = run(command, path, miri=True)
            elif changed:
                print("[10/10] Miri: no packages in escape-hatch paths", flush=True)
            else:
                print("[10/10] Miri: no changes", flush=True)
    except FileNotFoundError as error:
        print(f"{step} failed: missing executable {error}", file=sys.stderr)
        return 127
    except subprocess.CalledProcessError as error:
        print((cast("str | None", error.stdout) or ""), end="", file=sys.stderr)
        print(f"{step} failed (exit {error.returncode})", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, UnicodeError, ValueError, TypeError) as error:
        print(
            f"{step} failed: invalid governed content or runtime failure: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


def fixture_repo(source: Path, destination: Path) -> str:
    """Install a fixture into a temporary git repo with a trusted gate baseline."""
    _ = source.copy(destination)
    for name in ("clippy.toml", "rustfmt.toml", "deny.toml", "rust-toolchain.toml"):
        _ = (SKILL / "assets" / name).copy(destination / name)
    folder = destination / ".gate"
    folder.mkdir()
    _ = (SKILL / "assets/governance-check.py").copy(folder / "governance-check.py")
    _ = run(["git", "init", "--quiet"], destination)
    for key, value in (
        ("user.name", "Fixture verifier"),
        ("user.email", "fixture@example.invalid"),
        ("commit.gpgsign", "false"),
    ):
        _ = run(["git", "config", key, value], destination)
    # Commit an empty source baseline so mutations exercise every fixture function.
    sources = {
        file: file.read_text(encoding="utf-8") for file in destination.rglob("*.rs")
    }
    for file in sources:
        baseline = "//! Fixture baseline.\n"
        if file.name == "main.rs":
            baseline += "fn main() {}\n"
        _ = file.write_text(baseline, encoding="utf-8")
    _ = run(["git", "add", "."], destination)
    _ = run(["git", "commit", "--quiet", "-m", "Fixture baseline"], destination)
    for file, content in sources.items():
        _ = file.write_text(content, encoding="utf-8")
    return "HEAD"


def verify_diagnostics(diagnostics: str) -> None:
    """Require a known diagnostic for every deliberately broken category."""
    if "unknown lint" in diagnostics:
        raise RuntimeError("bad fixture emitted an unknown-lint diagnostic")
    for category, lint in EXPECTED.items():
        if lint not in diagnostics.replace("-", "_"):
            raise RuntimeError(f"bad fixture missing {category} diagnostic: {lint}")
        print(f"Verified {category}: {lint}")


def verify_inventory_cases(root: Path) -> None:
    """Exercise real compiled inventories against ancestor and Cargo discovery loss."""
    for name in ("ancestor", "lib-target"):
        repo = root / f"inventory-{name}"
        _ = fixture_repo(SKILL / "tests/fixtures/good", repo)
        _ = run(["git", "add", "."], repo)
        _ = run(["git", "commit", "--quiet", "-m", "Trusted test inventory"], repo)
        if name == "ancestor":
            source = repo / CORE / "src/lib.rs"
            content = source.read_text(encoding="utf-8")
            content = (
                content.replace(
                    "#[cfg(test)]", "#[cfg(any())]\nmod ancestor {\n#[cfg(test)]"
                )
                + "\n}\n"
            )
            _ = source.write_text(content, encoding="utf-8")
        else:
            with (repo / CORE / "Cargo.toml").open("a", encoding="utf-8") as stream:
                _ = stream.write("\n[lib]\ntest = false\n")
        try:
            _ = run(
                [
                    sys.executable,
                    str(SKILL / "assets/governance-check.py"),
                    "HEAD",
                    "--inventory",
                ],
                repo,
            )
        except subprocess.CalledProcessError as error:
            if "test inventory lost or newly ignored" not in cast("str", error.stdout):
                raise RuntimeError(
                    f"inventory case failed without inventory loss: {name}"
                ) from error
        else:
            raise RuntimeError(f"inventory case passed: {name}")
        worktrees = run(["git", "worktree", "list", "--porcelain"], repo)
        if worktrees.count("worktree ") != 1:
            raise RuntimeError("inventory baseline worktree leaked")
        print(f"Verified compiled test preservation: {name}")


def binary_only(repo: Path) -> None:
    """Reduce the good workspace to one dependency-free binary package."""
    shutil.rmtree(repo / CORE)
    for manifest, line in (
        (
            repo / "Cargo.toml",
            'fixture-core = { path = "crates/fixture-core", version = "0.0.0" }\n',
        ),
        (repo / "crates/fixture/Cargo.toml", "fixture-core.workspace = true\n"),
    ):
        text = manifest.read_text(encoding="utf-8")
        _ = manifest.write_text(text.replace(line, ""), encoding="utf-8")
    _ = (repo / "crates/fixture/src/main.rs").write_text(
        "//! Binary-only fixture.\nfn main() {}\n", encoding="utf-8"
    )
    _ = run(["cargo", "generate-lockfile", "--offline"], repo)


def verify_inventory_controls(root: Path) -> None:
    """Check binary-only, greenfield, lint debt, and doctest line movement."""
    for name in ("binary-only", "greenfield", "lint-debt", "doctest-comment-shift"):
        repo = root / name
        _ = fixture_repo(SKILL / "tests/fixtures/good", repo)
        source = repo / CORE / "src/lib.rs"
        if name == "binary-only":
            binary_only(repo)
        elif name == "lint-debt":
            capacity_doc = (
                "/// Reports whether a requested allocation fits within its "
                "available capacity.\n"
            )
            _ = source.write_text(
                source.read_text(encoding="utf-8").replace(capacity_doc, ""),
                encoding="utf-8",
            )
        elif name == "doctest-comment-shift":
            _ = source.write_text(
                """//! Fixture.



/// Examples.
/// ```ignore
/// assert!(true);
/// ```
/// ```
/// assert!(true);
/// ```
pub fn documented() {}
""",
                encoding="utf-8",
            )
            _ = (repo / "crates/fixture/src/main.rs").write_text(
                "//! Fixture binary.\nfn main() {}\n", encoding="utf-8"
            )
        _ = run(["git", "add", "."], repo)
        if name == "greenfield":
            # The trusted base keeps the root manifest but no member crates.
            _ = run(["git", "rm", "-r", "--cached", "--quiet", "crates"], repo)
        _ = run(["git", "commit", "--quiet", "-m", "Inventory control baseline"], repo)
        if name == "lint-debt":
            _ = source.write_text(
                (SKILL / "tests/fixtures/good" / CORE / "src/lib.rs").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
        elif name == "doctest-comment-shift":
            _ = source.write_text(
                "// ordinary comment\n" + source.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        checker = str(SKILL / "assets/governance-check.py")
        _ = run([sys.executable, checker, "HEAD", "--inventory"], repo)
        if name == "binary-only":
            _ = run([sys.executable, checker, "--doctests"], repo)
        print(f"Verified inventory positive control: {name}")


def verify_fixtures() -> int:
    """Prove good passes and every bad category is caught by the real tools."""
    with tempfile.TemporaryDirectory(prefix="rust-fixtures-") as temporary:
        root = Path(temporary)
        good = root / "good"
        base = fixture_repo(SKILL / "tests/fixtures/good", good)
        if gate(good, base):
            return 1
        verify_inventory_cases(root)
        verify_inventory_controls(root)
        bad = root / "bad"
        base = fixture_repo(SKILL / "tests/fixtures/bad", bad)
        if gate(bad, base) != 1:
            raise RuntimeError("bad fixture did not fail its gate")
        try:
            _ = run(COMMANDS[1][1], bad)
        except subprocess.CalledProcessError as error:
            diagnostics = cast("str", error.stdout)
        else:
            raise RuntimeError("bad fixture passed clippy")
        verify_diagnostics(diagnostics)
        try:
            _ = run(
                [sys.executable, str(SKILL / "assets/governance-check.py"), base], bad
            )
        except subprocess.CalledProcessError as error:
            for expected in (
                "escape hatch outside allowlist",
                "allow attribute added in src/governance.rs",
                "#[ignore] added",
            ):
                if expected not in cast("str", error.stdout):
                    raise RuntimeError(
                        f"missing governance violation: {expected}"
                    ) from error
        else:
            raise RuntimeError("bad fixture passed governance")
    print("Fixture verification passed")
    return 0


EVAL_TASKS = ("async", "library", "ffi", "retrofit")


def eval_setup(task: str, dest: Path) -> int:
    """Recreate a task's human-installed baseline without invoking Rust."""
    dest.mkdir(parents=True)
    _ = run(["git", "init", "--quiet", "--initial-branch=main"], dest)
    for key, value in (
        ("user.name", "eval"),
        ("user.email", "eval@example.invalid"),
        ("commit.gpgsign", "false"),
    ):
        _ = run(["git", "config", "--local", key, value], dest)
    if task == "retrofit":
        for source in (SKILL / "evals/files/retrofit").iterdir():
            _ = source.copy(dest / source.name)
        _ = run(["git", "add", "."], dest)
        _ = run(["git", "commit", "--quiet", "-m", "Legacy tally"], dest)
    assets = SKILL / "assets"
    for name in ("clippy.toml", "rustfmt.toml", "deny.toml", "rust-toolchain.toml"):
        _ = (assets / name).copy(dest / name)
    (dest / ".gate").mkdir()
    _ = (assets / "governance-check.py").copy(dest / ".gate/governance-check.py")
    if task == "ffi":
        _ = (SKILL / "evals/files/ffi/vendor").copy(dest / "vendor")
        _ = (dest / ".gate/escape-hatch-paths").write_text(
            "crates/*-ffi/*\n", encoding="utf-8"
        )
    manifest = dest / "Cargo.toml"
    prefix = ""
    if task == "retrofit":
        prefix = manifest.read_text(encoding="utf-8").rstrip() + "\n\n"
        if "lints" not in tomllib.loads(prefix):
            prefix += "[lints]\nworkspace = true\n\n"
        prefix += "[workspace]\n\n"
    else:
        _ = (dest / ".gitignore").write_text("target/\n", encoding="utf-8")
        prefix = '[workspace]\nresolver = "3"\n\n'
    lints = (assets / "workspace-lints.toml").read_text(encoding="utf-8")
    lines = lints.splitlines(keepends=True)
    while lines and lines[0].lstrip().startswith("#"):
        _ = lines.pop(0)
    profiles = (assets / "profiles.toml").read_text(encoding="utf-8")
    _ = manifest.write_text(
        prefix + "".join(lines).rstrip() + "\n\n" + profiles,
        encoding="utf-8",
    )
    _ = run(["git", "add", "."], dest)
    _ = run(["git", "commit", "--quiet", "-m", "Install human-owned gates"], dest)
    print(f"Created {dest}; eval prompt id: {EVAL_TASKS.index(task) + 1}")
    return 0


def main() -> int:
    """Parse the public CLI and map runtime failures to documented exit codes."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    gate_parser = commands.add_parser("gate", help="Run the ordered workspace gate")
    _ = gate_parser.add_argument("--base", default="origin/main")
    _ = gate_parser.add_argument("--path", type=Path, default=Path.cwd())
    _ = commands.add_parser("verify-fixtures", help="Verify good/bad crates with Rust")
    setup_parser = commands.add_parser(
        "eval-setup", help="Recreate an evaluation baseline"
    )
    _ = setup_parser.add_argument("--task", choices=EVAL_TASKS, required=True)
    _ = setup_parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args(namespace=Options())
    try:
        if args.command == "eval-setup":
            if args.dest.exists() or args.dest.is_symlink():
                parser.error("--dest must not exist")
            return eval_setup(args.task, args.dest.resolve())
        if args.command == "gate":
            if not args.path.is_dir():
                parser.error("--path must name an existing directory")
            return gate(args.path.resolve(), args.base)
        return verify_fixtures()
    except FileNotFoundError as error:
        print(f"Missing executable or file: {error}", file=sys.stderr)
        return 127
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
