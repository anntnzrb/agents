# Copyright (c) 2026 anntnzrb
"""Exercise governance rules against real temporary git histories."""

import subprocess
import sys
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[1] / "assets/governance-check.py"


def git(root: Path, *args: str) -> str:
    """Run git in an isolated test repository."""
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Create a trusted baseline containing tests and gate configuration."""
    _ = git(tmp_path, "init", "--quiet")
    for key, value in (
        ("user.name", "Test"),
        ("user.email", "test@example.invalid"),
        ("commit.gpgsign", "false"),
    ):
        _ = git(tmp_path, "config", key, value)
    for name, content in {
        "Cargo.toml": (
            '[package]\nname = "example"\n\n'
            '[workspace.lints.rust]\nunsafe_code = "deny"\n\n'
            "[profile.release]\noverflow-checks = true\n"
        ),
        "src/lib.rs": (
            '// baseline\n#[test]\nfn check() { assert!(true, "baseline"); }\n'
        ),
        "tests/it.rs": "// integration tests\n",
        ".gate/escape-hatch-paths": "src/adapter.rs\n",
        "deny.toml": '[bans]\nwildcards = "deny"\n',
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(content, encoding="utf-8")
    _ = git(tmp_path, "add", ".")
    _ = git(tmp_path, "commit", "--quiet", "-m", "baseline")
    return tmp_path


def check(root: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the standalone checker as a subprocess."""
    return subprocess.run(
        [sys.executable, str(CHECKER), "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.mark.parametrize("name", ["src/lib.rs", "Cargo.toml", "src/adapter.rs"])
def test_allowed_changes(repository: Path, name: str) -> None:
    """Ordinary changes and approved escape hatches pass."""
    path = repository / name
    with path.open("a", encoding="utf-8") as stream:
        _ = stream.write(
            "\n// unsafe adapter\n"
            if name.endswith("adapter.rs")
            else "\n# comment\n"
            if name.endswith("toml")
            else "\n// ordinary change\n"
        )
    if name.endswith("toml"):
        # Change package metadata, outside any protected table.
        _ = path.write_text(
            path.read_text(encoding="utf-8")
            .replace('name = "example"', 'name = "renamed"')
            .removesuffix("\n# comment\n"),
            encoding="utf-8",
        )
    _ = git(repository, "add", ".")
    result = check(repository)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("deny.toml", "[bans]\n", "protected gate file changed"),
        (
            "Cargo.toml",
            '[lints.rust]\nunsafe_code = "allow"\n',
            "[lints] or [profile] changed",
        ),
        (
            "Cargo.toml",
            "[profile.release]\noverflow-checks = false\n",
            "[lints] or [profile] changed",
        ),
        (
            "src/lib.rs",
            "#[test]\n#[ignore]\nfn check() { assert!(true); }\n",
            "#[ignore] added",
        ),
        ("src/lib.rs", "// deleted test\n", "net loss of #[test] functions"),
        ("src/lib.rs", "#[test]\nfn check() {}\n", "net loss of assertions"),
        ("src/lib.rs", "// unsafe new operation\n", "escape hatch outside allowlist"),
        (
            "src/lib.rs",
            '#![expect(dead_code, reason = "test")]\n',
            "escape hatch outside allowlist",
        ),
    ],
)
def test_rejected_changes(
    repository: Path, name: str, content: str, message: str
) -> None:
    """Each governance rule fails on the actual changed content."""
    _ = (repository / name).write_text(content, encoding="utf-8")
    result = check(repository)
    assert result.returncode == 1
    assert message in result.stderr


def test_deleted_test_file(repository: Path) -> None:
    """Deleting a test file fails independently of assertion counts."""
    (repository / "tests/it.rs").unlink()
    result = check(repository)
    assert result.returncode == 1
    assert "test file deleted" in result.stderr


def test_cannot_self_authorize(repository: Path) -> None:
    """A modified allowlist cannot approve its own escape hatch."""
    _ = (repository / ".gate/escape-hatch-paths").write_text(
        "src/*\n", encoding="utf-8"
    )
    _ = (repository / "src/lib.rs").write_text("// unsafe\n", encoding="utf-8")
    result = check(repository)
    assert "escape hatch outside allowlist" in result.stderr


def test_invalid_base_fails(repository: Path) -> None:
    """An invalid base never silently produces an empty successful diff."""
    result = subprocess.run(
        [sys.executable, str(CHECKER), "missing-ref"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 1


@pytest.mark.parametrize(
    ("path", "attribute", "message"),
    [
        (
            "src/lib.rs",
            '#![allow(dead_code, reason = "compat")]\n',
            "allow attribute added",
        ),
        ("src/adapter.rs", "#[allow(dead_code)]\n", "allow attribute added"),
        (
            "src/lib.rs",
            "#[cfg_attr(all(), cfg_attr(all(), allow(dead_code)))]\n",
            "allow attribute added",
        ),
        ("src/lib.rs", "# ! [\n allow(\n dead_code\n )\n]\n", "allow attribute added"),
        (
            "src/lib.rs",
            '#[cfg_attr(all(), expect(dead_code, reason = "compat"))]\n',
            "escape hatch outside allowlist",
        ),
        (
            "src/lib.rs",
            '#[\nexpect\n(dead_code, reason = "compat")\n]\n',
            "escape hatch outside allowlist",
        ),
    ],
)
def test_complete_suppression_attributes(
    repository: Path, path: str, attribute: str, message: str
) -> None:
    """Inner, conditional, and multiline attributes obey the same policy."""
    file = repository / path
    _ = file.write_text(
        attribute
        + (file.read_text(encoding="utf-8") if file.exists() else "fn adapter() {}\n"),
        encoding="utf-8",
    )
    _ = git(repository, "add", ".")
    result = check(repository)
    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize(
    "attribute", ['#[cfg_attr(all(), ignore = "compat")]\n', "#[cfg(any())]\n"]
)
def test_conditional_test_disabling(repository: Path, attribute: str) -> None:
    """A conditional attribute cannot silently remove an existing test."""
    file = repository / "src/lib.rs"
    _ = file.write_text(attribute + file.read_text(encoding="utf-8"), encoding="utf-8")
    _ = git(repository, "add", ".")
    result = check(repository)
    assert result.returncode == 1
    assert "ignore" in result.stderr or "test condition" in result.stderr


def test_condition_on_existing_test_module(repository: Path) -> None:
    """Test modules cannot gain a condition even when all inner lines survive."""
    file = repository / "src/lib.rs"
    original = "#[cfg(test)]\nmod tests {\n#[test]\nfn check() { assert!(true); }\n}\n"
    _ = file.write_text(original, encoding="utf-8")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "test module")
    _ = file.write_text(
        original.replace("#[cfg(test)]", "#[cfg(all(test, any()))]"), encoding="utf-8"
    )
    assert "test condition" in check(repository).stderr


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("deny.toml", "old-deny.toml", "protected gate file changed"),
        ("tests/it.rs", "src/unused_tests.rs", "test file deleted"),
    ],
)
def test_renames_cannot_hide_removals(
    repository: Path, old: str, new: str, message: str
) -> None:
    """Moving a protected gate or discovered test still checks its old path."""
    _ = git(repository, "mv", old, new)
    result = check(repository)
    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize(
    "section",
    [
        "[ profile . test ]\noverflow-checks = false\n",
        "profile.test = { overflow-checks = false }\n",
    ],
)
def test_semantic_manifest_gate_change(repository: Path, section: str) -> None:
    """Alternative valid TOML spellings cannot evade profile protection."""
    file = repository / "Cargo.toml"
    _ = file.write_text(
        section + "\n" + file.read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = check(repository)
    assert result.returncode == 1
    assert "[lints] or [profile] changed" in result.stderr


@pytest.mark.parametrize("lints", ["", '[ lints . clippy ]\nunwrap_used = "allow"\n'])
def test_new_member_must_inherit_lints(repository: Path, lints: str) -> None:
    """New member packages inherit the workspace policy without overrides."""
    member = repository / "member/Cargo.toml"
    member.parent.mkdir()
    _ = member.write_text('[package]\nname = "member"\n' + lints, encoding="utf-8")
    _ = git(repository, "add", ".")
    result = check(repository)
    assert result.returncode == 1
    assert "inherit workspace lints" in result.stderr


def test_semantic_manifest_formatting_passes(repository: Path) -> None:
    """Equivalent TOML formatting is not a semantic gate change."""
    file = repository / "Cargo.toml"
    _ = file.write_text(
        file.read_text(encoding="utf-8").replace(
            "[workspace.lints.rust]", "[ workspace . lints . rust ]"
        ),
        encoding="utf-8",
    )
    assert check(repository).returncode == 0


def test_invalid_manifest_fails_closed(repository: Path) -> None:
    """Invalid TOML cannot yield an empty successful policy comparison."""
    _ = (repository / "Cargo.toml").write_text("[package\n", encoding="utf-8")
    assert "invalid TOML" in check(repository).stderr


@pytest.mark.parametrize(
    "name", [".gitattributes", "src/.gitattributes", ".gitmodules", "src/.gitmodules"]
)
def test_git_metadata_protected(repository: Path, name: str) -> None:
    """Attributes and module metadata are human-owned gate inputs at any depth."""
    _ = (repository / name).write_text("*.rs -diff\n", encoding="utf-8")
    _ = git(repository, "add", ".")
    result = check(repository)
    assert result.returncode == 1
    assert "protected gate file changed" in result.stderr


def test_binary_attributes_do_not_hide_rust(repository: Path) -> None:
    """Forced text diffs expose source escapes even under binary attributes."""
    _ = (repository / ".gitattributes").write_text("*.rs -diff\n", encoding="utf-8")
    file = repository / "src/lib.rs"
    _ = file.write_text(
        '#![expect(dead_code, reason = "compat")]\n' + file.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _ = git(repository, "add", ".")
    assert "escape hatch outside allowlist" in check(repository).stderr


def test_non_ascii_path_cannot_inherit_authorization(repository: Path) -> None:
    """Quoted second-file headers cannot reuse the first file's authorization."""
    _ = (repository / "src/adapter.rs").write_text(
        '#[path = "zé.rs"]\nmod extra;\n', encoding="utf-8"
    )
    _ = (repository / "src/zé.rs").write_text(
        '#![expect(dead_code, reason = "compat")]\n', encoding="utf-8"
    )
    _ = git(repository, "add", ".")
    result = check(repository)
    assert result.returncode == 1
    assert "escape hatch outside allowlist in src/zé.rs" in result.stderr


def test_untracked_source_is_checked_without_index_changes(repository: Path) -> None:
    """Untracked, non-ignored Rust participates without staging side effects."""
    before = git(repository, "ls-files", "--stage", "-z")
    _ = (repository / "src/new.rs").write_text(
        "#![allow(dead_code)]\n", encoding="utf-8"
    )
    result = check(repository)
    assert result.returncode == 1
    assert "allow attribute added" in result.stderr
    assert git(repository, "ls-files", "--stage", "-z") == before


def test_new_member_with_inheritance_passes(repository: Path) -> None:
    """A new package can join without introducing its own lint policy."""
    member = repository / "member/Cargo.toml"
    member.parent.mkdir()
    _ = member.write_text(
        '[package]\nname = "member"\n[lints]\nworkspace = true\n', encoding="utf-8"
    )
    assert check(repository).returncode == 0


def test_multiline_existing_attribute_is_scanned_whole(repository: Path) -> None:
    """Adding a nested expectation scans the unchanged start of its attribute."""
    file = repository / "src/lib.rs"
    original = "#[cfg_attr(\nall(),\ninline,\n)]\n" + file.read_text(encoding="utf-8")
    _ = file.write_text(original, encoding="utf-8")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "existing multiline attribute")
    _ = file.write_text(
        original.replace("inline,", 'inline,\nexpect(dead_code, reason = "fixture"),'),
        encoding="utf-8",
    )
    assert "escape hatch outside allowlist" in check(repository).stderr


def test_approved_conditional_expectation_passes(repository: Path) -> None:
    """The trusted allowlist permits nested reasoned expectations."""
    _ = (repository / "src/adapter.rs").write_text(
        '#[cfg_attr(all(), expect(dead_code, reason = "fixture"))]\nfn adapter() {}\n',
        encoding="utf-8",
    )
    assert check(repository).returncode == 0


def test_attribute_examples_in_comments_and_literals_pass(repository: Path) -> None:
    """Documentation and raw string examples are not executable attributes."""
    file = repository / "src/lib.rs"
    with file.open("a", encoding="utf-8") as stream:
        _ = stream.write("""
// #[allow(dead_code)]
/* outer /* #[expect(dead_code)] */ comment */
const EXAMPLE: &str = r###"#[allow(dead_code)] #[ignore]"###;
const QUOTED: &str = "#[cfg_attr(all(), allow(dead_code))]";
""")
    assert check(repository).returncode == 0


def test_same_test_name_in_distinct_modules(repository: Path) -> None:
    """A condition on one test cannot authorize the same name in another module."""
    file = repository / "src/lib.rs"
    original = """
#[cfg(test)]
mod first {
    #[cfg(all())]
    #[test]
    fn check() { assert!(true); }
}
#[cfg(test)]
mod second {
    #[test]
    fn check() { assert!(true); }
}
"""
    _ = file.write_text(original, encoding="utf-8")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "separate test identities")
    _ = file.write_text(
        original.replace("mod second {", "mod second {\n    #[cfg(all())]"),
        encoding="utf-8",
    )
    assert "test condition" in check(repository).stderr


@pytest.mark.parametrize("staged", [False, True])
def test_symlinks_rejected(repository: Path, *, staged: bool) -> None:
    """A changed symlink cannot hide source behind target-text line coordinates."""
    _ = (repository / "payload.txt").write_text(
        "// first\n#![allow(dead_code)]\npub unsafe fn hidden() {}\n", encoding="utf-8"
    )
    (repository / "src/linked.rs").symlink_to("../payload.txt")
    if staged:
        _ = git(repository, "add", ".")
    assert "symlink outside allowlist" in check(repository).stderr


@pytest.mark.parametrize(
    "template",
    [
        """macro_rules! define { ($hash:tt) => {
$hash ! [allow(dead_code)] fn hidden() {} }; }
define!(#);
""",
        """macro_rules! decorated { ($attr:meta) => {
#[$attr] fn example() {} }; }
decorated!(inline);
""",
    ],
)
def test_attribute_producing_macro_policy(repository: Path, template: str) -> None:
    """Both substituted inner attributes and metadata templates require approval."""
    file = repository / "src/lib.rs"
    with file.open("a", encoding="utf-8") as stream:
        _ = stream.write(template)
    assert "attribute-producing macro outside allowlist" in check(repository).stderr


def test_approved_metadata_macro(repository: Path) -> None:
    """A template in a trusted-allowlisted path is parsed as a token tree."""
    _ = (repository / "src/adapter.rs").write_text(
        "macro_rules! decorated { ($attr:meta) => { #[$attr] fn example() {} }; }\n",
        encoding="utf-8",
    )
    assert check(repository).returncode == 0


def test_dependency_only_manifest_edit(repository: Path) -> None:
    """Adding dependency configuration preserves semantic lint/profile gates."""
    with (repository / "Cargo.toml").open("a", encoding="utf-8") as stream:
        _ = stream.write('\n[dependencies]\nexample = "1"\n')
    assert check(repository).returncode == 0


@pytest.mark.parametrize(
    "definition",
    ["macro_rules! define [", "macro_rules ! define {", "macro_rules\n! define ("],
)
@pytest.mark.parametrize("approved", [False, True])
def test_all_macro_definition_spellings(
    repository: Path, definition: str, *, approved: bool
) -> None:
    """All definition delimiters and whitespace forms use the same ownership rule."""
    closing = {"[": "]", "{": "}", "(": ")"}[definition[-1]]
    source = (
        definition
        + """
    ($hash:tt) => {
        pub mod suppressed {
            $hash ! [allow(clippy::unwrap_used, reason = "compat")]
            pub fn hidden(value: Option<u8>) -> u8 { value.unwrap() }
        }
    };
"""
        + closing
        + ";\ndefine!(#);\n"
    )
    path = "src/adapter.rs" if approved else "src/lib.rs"
    with (repository / path).open("a", encoding="utf-8") as stream:
        _ = stream.write(source)
    result = check(repository)
    if approved:
        assert result.returncode == 0, result.stderr
    else:
        assert "macro outside allowlist" in result.stderr


@pytest.mark.parametrize("approved", [False, True])
def test_existing_symlink_requires_approval(
    repository: Path, *, approved: bool
) -> None:
    """A target-only edit cannot hide executable source behind a pre-existing link."""
    path = "src/adapter.rs" if approved else "src/linked.rs"
    payload = repository / "payload.txt"
    _ = payload.write_text("pub fn value() {}\n", encoding="utf-8")
    (repository / path).symlink_to("../payload.txt")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "existing source link")
    _ = payload.write_text(
        "#![allow(dead_code)]\npub fn value() {}\n", encoding="utf-8"
    )
    result = check(repository)
    if approved:
        assert result.returncode == 0, result.stderr
    else:
        assert "symlink outside allowlist" in result.stderr


@pytest.mark.parametrize("ignored", [False, True])
def test_only_proposed_untracked_symlinks_checked(
    repository: Path, *, ignored: bool
) -> None:
    """Ignored build output such as a `nix build` result link is not proposed."""
    _ = (repository / ".gitignore").write_text(
        "/result\n" if ignored else "/other\n", encoding="utf-8"
    )
    _ = git(repository, "add", ".gitignore")
    _ = git(repository, "commit", "--quiet", "-m", "ignore build output")
    (repository / "result").symlink_to("/nix/store/example")
    result = check(repository)
    if ignored:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1
        assert "symlink outside allowlist in result" in result.stderr


@pytest.mark.parametrize("name", ["li\rnk", "li\r\nnk"])
def test_carriage_return_symlink_names_rejected(repository: Path, name: str) -> None:
    """Git path output keeps exact filesystem names without newline translation."""
    (repository / name).symlink_to("/nonexistent")
    result = check(repository)
    assert result.returncode == 1
    assert "symlink outside allowlist" in result.stderr


def test_symlinked_ancestor_of_tracked_path_rejected(
    repository: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A tracked directory replaced by a link cannot serve outside content."""
    outside = tmp_path_factory.mktemp("outside") / "src"
    _ = (repository / "src").rename(outside)
    (repository / "src").symlink_to(outside)
    result = check(repository)
    assert result.returncode == 1
    assert "symlink outside allowlist in src" in result.stderr


@pytest.mark.parametrize("ignored", [False, True])
def test_untracked_embedded_repository_symlinks(
    repository: Path, *, ignored: bool
) -> None:
    """Git lists an untracked nested repository as one entry; its links still count."""
    _ = (repository / ".gitignore").write_text(
        "/build/\n" if ignored else "/other/\n", encoding="utf-8"
    )
    _ = git(repository, "add", ".gitignore")
    _ = git(repository, "commit", "--quiet", "-m", "ignore build output")
    module = repository / "build/vendor"
    module.mkdir(parents=True)
    _ = git(module, "init", "--quiet")
    (module / "linked").symlink_to("/nonexistent")
    result = check(repository)
    if ignored:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1
        assert "symlink outside allowlist in build/vendor/linked" in result.stderr


def test_indexed_symlink_below_symlinked_parent_reported(
    repository: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Indexed links skip ignore classification, so Git cannot abort the check."""
    (repository / "dir").mkdir()
    (repository / "dir/link").symlink_to("/nonexistent")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "linked directory")
    outside = tmp_path_factory.mktemp("outside") / "dir"
    _ = (repository / "dir").rename(outside)
    (repository / "dir").symlink_to(outside)
    result = check(repository)
    assert result.returncode == 1
    assert "symlink outside allowlist in dir\n" in result.stderr
    assert "symlink outside allowlist in dir/link" in result.stderr


def test_submodule_update_symlink_rejected(repository: Path) -> None:
    """Links inside a submodule working tree remain proposed content."""
    module = repository / "dep"
    module.mkdir()
    _ = git(module, "init", "--quiet")
    for key, value in (
        ("user.name", "Test"),
        ("user.email", "test@example.invalid"),
        ("commit.gpgsign", "false"),
    ):
        _ = git(module, "config", key, value)
    _ = (module / "README").write_text("dependency\n", encoding="utf-8")
    _ = git(module, "add", ".")
    _ = git(module, "commit", "--quiet", "-m", "dependency")
    _ = git(repository, "add", "dep")
    _ = git(repository, "commit", "--quiet", "-m", "submodule")
    (module / "linked").symlink_to("README")
    _ = git(module, "add", ".")
    _ = git(module, "commit", "--quiet", "-m", "link")
    _ = git(repository, "add", "dep")
    result = check(repository)
    assert result.returncode == 1
    assert "symlink outside allowlist in dep/linked" in result.stderr


@pytest.mark.parametrize("approved", [False, True])
def test_proc_macro_package_changes(repository: Path, *, approved: bool) -> None:
    """Every changed path inside a proc-macro package requires human authorization."""
    manifest = repository / "Cargo.toml"
    with manifest.open("a", encoding="utf-8") as stream:
        _ = stream.write("\n[lib]\nproc-macro = true\n")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "proc macro package")
    path = "src/adapter.rs" if approved else "src/lib.rs"
    with (repository / path).open("a", encoding="utf-8") as stream:
        _ = stream.write("// ordinary implementation change\n")
    result = check(repository)
    if approved:
        assert result.returncode == 0, result.stderr
    else:
        assert "proc-macro package change outside allowlist" in result.stderr


def test_plain_mode_discloses_all_skipped_checks(repository: Path) -> None:
    """Plain mode names all skipped compiled checks and routes them to CI."""
    result = check(repository)
    assert result.returncode == 0
    assert "compiled test inventory" in result.stderr
    assert "member resolution" in result.stderr
    assert "doctest comparison" in result.stderr
    assert "CI runs them" in result.stderr


def test_ordinary_tt_passthrough_macro(repository: Path) -> None:
    """An ordinary tt passthrough needs no macro ownership exception."""
    with (repository / "src/lib.rs").open("a", encoding="utf-8") as stream:
        _ = stream.write(
            """macro_rules! pass { ($($t:tt)*) => { $($t)* }; }
pass!(fn ordinary() {});
"""
        )
    assert check(repository).returncode == 0


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "macro_rules! make { ($hash:tt) => { $hash ! [inline] fn value() {} }; }\n",
            "macro outside allowlist",
        ),
        ("external_macro!(#);\n", "bare hash token"),
    ],
)
def test_hash_construction_and_invocation_separately(
    repository: Path, source: str, message: str
) -> None:
    """Definition-side construction and bare invocation hashes fail independently."""
    with (repository / "src/lib.rs").open("a", encoding="utf-8") as stream:
        _ = stream.write(source)
    result = check(repository)
    assert result.returncode == 1
    assert message in result.stderr


def test_unbounded_macro_fails_closed(repository: Path) -> None:
    """A recognized macro definition without a balanced body cannot pass."""
    with (repository / "src/lib.rs").open("a", encoding="utf-8") as stream:
        _ = stream.write("macro_rules ! broken [ () => { #[inline] fn f() {} };\n")
    assert "macro" in check(repository).stderr


@pytest.mark.parametrize(
    "attribute",
    [
        '#[cfg_attr(miri, ignore = "FFI call")] ',
        '#[cfg_attr(miri, ignore = r#"FFI call"#)] ',
        '#[cfg_attr(all(), cfg_attr(miri, ignore = "FFI call"))] ',
        '#[cfg_attr(\nmiri,\nignore = "FFI call"\n)] ',
        "#[cfg_attr(miri, inline)] ",
        "#![cfg(not(miri))] ",
        "#[cfg(miri)] ",
        "#[mutants::skip] ",
        "#[cfg_attr(all(), mutants::skip)] ",
    ],
)
@pytest.mark.parametrize("approved", [False, True])
def test_governed_miri_and_mutants_attributes(
    repository: Path, attribute: str, *, approved: bool
) -> None:
    """Miri exclusions and mutation skips require trusted path approval."""
    path = "src/adapter.rs" if approved else "src/lib.rs"
    with (repository / path).open("a", encoding="utf-8") as stream:
        _ = stream.write(f"\n{attribute}\nfn adapter() {{}}\n")
    result = check(repository)
    if approved:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1
        assert "escape hatch outside allowlist" in result.stderr


@pytest.mark.parametrize("reason", ["", ' = ""', ' = "   "'])
def test_miri_ignore_requires_reason(repository: Path, reason: str) -> None:
    """Even an approved Miri exclusion must state a nonempty reason."""
    _ = (repository / "src/adapter.rs").write_text(
        f"#[cfg_attr(miri, ignore{reason})]\nfn adapter() {{}}\n", encoding="utf-8"
    )
    result = check(repository)
    assert result.returncode == 1
    assert "non-empty reason" in result.stderr


@pytest.mark.parametrize("name", [".cargo/mutants.toml", "mutants.toml"])
@pytest.mark.parametrize("operation", ["add", "modify", "delete", "rename"])
def test_mutants_configuration_protected(
    repository: Path, name: str, operation: str
) -> None:
    """Mutation exclusions cannot be added or altered through gate config."""
    config = repository / name
    config.parent.mkdir(parents=True, exist_ok=True)
    _ = config.write_text('exclude_re = ["adapter"]\n', encoding="utf-8")
    if operation != "add":
        _ = git(repository, "add", ".")
        _ = git(repository, "commit", "--quiet", "-m", "trusted mutation config")
        if operation == "modify":
            _ = config.write_text('exclude_re = [".*"]\n', encoding="utf-8")
        elif operation == "delete":
            config.unlink()
        else:
            _ = config.rename(repository / "renamed.toml")
    result = check(repository)
    assert result.returncode == 1
    assert f"protected gate file changed: {name}" in result.stderr


@pytest.mark.parametrize(
    "attribute",
    [
        "#[should_panic]",
        '#[should_panic(expected = "x")]',
        '#[cfg_attr(all(), should_panic(expected = "x"))]',
    ],
)
@pytest.mark.parametrize("approved", [False, True])
def test_should_panic_rejected(
    repository: Path, attribute: str, *, approved: bool
) -> None:
    """The zero-panic policy applies in approved paths and nested attributes."""
    path = "src/adapter.rs" if approved else "src/lib.rs"
    with (repository / path).open("a", encoding="utf-8") as stream:
        _ = stream.write(f"\n#[test]\n{attribute}\nfn panic_test() {{}}\n")
    result = check(repository)
    assert result.returncode == 1
    assert "zero-panic policy" in result.stderr
    assert "assert Result/Option values" in result.stderr


@pytest.mark.parametrize(
    "attribute",
    ['#[cfg_attr(miri, ignore = "FFI call")]', "#[cfg(not(miri))]"],
)
def test_approved_miri_exclusion_on_existing_test(
    repository: Path, attribute: str
) -> None:
    """Trusted Miri exclusions can be added to existing FFI tests."""
    file = repository / "src/adapter.rs"
    original = '#[test]\nfn adapter() { assert!(true, "baseline"); }\n'
    _ = file.write_text(original, encoding="utf-8")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "trusted adapter test")
    _ = file.write_text(f"{attribute}\n{original}", encoding="utf-8")
    result = check(repository)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("#![cfg(not(miri))]", "escape hatch outside allowlist"),
        ("#[should_panic]", "zero-panic policy"),
        ("#[expect(dead_code)]", "escape hatch outside allowlist"),
        ("pub unsafe fn dormant() {}", "escape hatch outside allowlist"),
        ("#[mutants::skip]", "escape hatch outside allowlist"),
        ("#[allow(dead_code)]", "allow attribute added"),
        ("#[ignore]", "#[ignore] added"),
        ("const FLAG: bool = cfg ! ( miri );", "escape hatch outside allowlist"),
        ('include!("payload.inc");', "escape hatch outside allowlist"),
        ('#[path = "payload.inc"]', "escape hatch outside allowlist"),
    ],
)
def test_comment_delimiter_deletion_activates_policy(
    repository: Path, source: str, message: str
) -> None:
    """Removing only comment delimiters cannot activate forbidden Rust silently."""
    file = repository / "src/lib.rs"
    original = file.read_text(encoding="utf-8")
    _ = file.write_text(f"/*\n{source}\n*/\n{original}", encoding="utf-8")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "dormant policy source")
    _ = file.write_text(f"{source}\n{original}", encoding="utf-8")
    result = check(repository)
    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize(
    "source",
    [
        'include ! ("payload.inc");',
        '#[path = "payload.inc"]\nmod payload;',
        "const FLAG: bool = cfg ! ( miri );",
    ],
)
def test_source_inputs_and_cfg_macro_require_approval(
    repository: Path, source: str, *, approved: bool
) -> None:
    """Source indirection and runtime Miri branches share the trusted path boundary."""
    path = "src/adapter.rs" if approved else "src/lib.rs"
    with (repository / path).open("a", encoding="utf-8") as stream:
        _ = stream.write(f"\n{source}\n")
    result = check(repository)
    if approved:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 1
        assert "escape hatch outside allowlist" in result.stderr


def test_approved_macro_cannot_emit_should_panic(repository: Path) -> None:
    """An approved macro body still obeys the unconditional zero-panic policy."""
    _ = (repository / "src/adapter.rs").write_text(
        """macro_rules! panic_case {
    () => {
        #[test]
        #[should_panic]
        fn boom() { std::panic::resume_unwind(Box::new("expected")); }
    };
}
panic_case!();
""",
        encoding="utf-8",
    )
    result = check(repository)
    assert result.returncode == 1
    assert "zero-panic policy" in result.stderr


@pytest.mark.parametrize("prefix", ["cargo:", "cargo::"])
@pytest.mark.parametrize("activate_comment", [False, True])
def test_build_script_cfg_requires_approval(
    repository: Path, prefix: str, *, activate_comment: bool
) -> None:
    """Raw build-script cfg emissions cannot bypass masking or deletion checks."""
    file = repository / "build.rs"
    line = f'fn main() {{ println!("{prefix}rustc-cfg=miri_alias"); }}\n'
    if activate_comment:
        _ = file.write_text(f"/*\n{line}*/\n", encoding="utf-8")
        _ = git(repository, "add", ".")
        _ = git(repository, "commit", "--quiet", "-m", "dormant build script")
    _ = file.write_text(line, encoding="utf-8")
    result = check(repository)
    assert result.returncode == 1
    assert "build script" in result.stderr


@pytest.mark.parametrize("operation", ["add", "modify", "delete", "rename"])
def test_build_script_changes_require_approval(
    repository: Path, operation: str
) -> None:
    """Every build-script file change is privileged, regardless of its contents."""
    file = repository / "build.rs"
    if operation != "add":
        _ = file.write_text("fn main() {}\n", encoding="utf-8")
        _ = git(repository, "add", ".")
        _ = git(repository, "commit", "--quiet", "-m", "trusted build script")
    if operation in {"add", "modify"}:
        _ = file.write_text(
            'fn main() { println!("cargo:rerun-if-changed=x"); }\n', encoding="utf-8"
        )
    elif operation == "delete":
        file.unlink()
    else:
        _ = file.rename(repository / "old.rs")
    result = check(repository)
    assert result.returncode == 1
    assert "build script" in result.stderr


def test_approved_build_script_change(repository: Path) -> None:
    """A trusted escape-hatch path permits build-script changes."""
    _ = (repository / ".gate/escape-hatch-paths").write_text(
        "build.rs\n", encoding="utf-8"
    )
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "approve build script")
    _ = (repository / "build.rs").write_text("fn main() {}\n", encoding="utf-8")
    assert check(repository).returncode == 0


@pytest.mark.parametrize(
    "predicate", ["cfg![miri]", "cfg!{ not(miri) }", "cfg!(any(test, miri))"]
)
def test_miri_cfg_macro_delimiters(repository: Path, predicate: str) -> None:
    """All cfg macro delimiters and nested Miri predicates require approval."""
    _ = (repository / "src/other.rs").write_text(
        f"const FLAG: bool = {predicate};\n", encoding="utf-8"
    )
    result = check(repository)
    assert result.returncode == 1
    assert "cfg!(miri)" in result.stderr


def test_governed_attribute_argument_change(repository: Path) -> None:
    """Broadening an existing Miri ignore cannot reuse its occurrence count."""
    file = repository / "src/other.rs"
    original = '#[cfg_attr(miri, ignore = "a")]\nfn other() {}\n'
    _ = file.write_text(original, encoding="utf-8")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "trusted conditional ignore")
    _ = file.write_text(
        original.replace("cfg_attr(miri,", "cfg_attr(any(test, miri),"),
        encoding="utf-8",
    )
    result = check(repository)
    assert result.returncode == 1
    assert "escape hatch" in result.stderr


def test_unchanged_governed_attribute_move_within_file_is_allowed_residual(
    repository: Path,
) -> None:
    """An unchanged occurrence moving between items is an allowed residual."""
    file = repository / "src/other.rs"
    attribute = '#[cfg_attr(miri, ignore = "a")]\n'
    _ = file.write_text(attribute + "fn first() {}\nfn second() {}\n", encoding="utf-8")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "trusted conditional ignore")
    _ = file.write_text(
        "fn first() {}\n" + attribute + "fn second() {}\n", encoding="utf-8"
    )
    result = check(repository)
    assert result.returncode == 0, result.stderr


def test_governed_attribute_argument_deletion(repository: Path) -> None:
    """Deleting an argument line changes semantics without any added source lines."""
    file = repository / "src/other.rs"
    original = "#[cfg_attr(all(\nany(),\n), should_panic)]\nfn other() {}\n"
    _ = file.write_text(original, encoding="utf-8")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "trusted inactive panic attribute")
    _ = file.write_text(original.replace("any(),\n", ""), encoding="utf-8")
    result = check(repository)
    assert result.returncode == 1
    assert "zero-panic policy" in result.stderr


def test_governed_macro_argument_change(repository: Path) -> None:
    """A trusted include occurrence does not approve a different source argument."""
    file = repository / "src/other.rs"
    _ = file.write_text('include!("old.rs");\n', encoding="utf-8")
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "trusted include")
    _ = file.write_text('include!("new.rs");\n', encoding="utf-8")
    result = check(repository)
    assert result.returncode == 1
    assert "include!" in result.stderr


@pytest.mark.parametrize("style", ["///", "//!", "/**", "/*!", "doc", "raw_doc"])
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Pure Adler-32, free of unsafe code.", ""),
        ("Mention #[should_panic] in prose.", ""),
        ("```rust\nunsafe { core::hint::unreachable_unchecked() }\n```", "unsafe"),
        ("~~~anything\n# #[should_panic]\n~~~", "zero-panic policy"),
        ("```\nunsafe {}", "unsafe"),
        ("```\n#[expect(dead_code)]\n```", "expect"),
        ("```\n#[cfg(miri)]\n```", "Miri"),
        ('```\nlet text = "unsafe"; // unsafe\n```', ""),
    ],
)
def test_doc_comment_governance(
    repository: Path, style: str, text: str, message: str
) -> None:
    """Govern fenced doctest code while ignoring prose in every doc syntax."""
    if style in {"///", "//!"}:
        source = "\n".join(f"{style} {line}" for line in text.splitlines())
    elif style in {"/**", "/*!"}:
        source = (
            style
            + "\n"
            + "\n".join(f" * {line}" for line in text.splitlines())
            + "\n */"
        )
    elif style == "raw_doc":
        source = f'#[doc = r##"{text}"##]'
    else:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        source = f'#[doc = "{escaped}"]'
    with (repository / "src/lib.rs").open("a", encoding="utf-8") as stream:
        _ = stream.write(f"\n{source}\nfn documented() {{}}\n")
    result = check(repository)
    if message:
        assert result.returncode == 1
        assert message in result.stderr
    else:
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source",
    [
        r'#[doc = "```\nu\u{6e}safe {}\n```"]',
        r'#[doc = "```\n#[should_\x70anic]\n```"]',
        "/// ````rust\n/// ```\n/// unsafe {}",
        "/// ```\n/// #\n/// # #[should_panic]\n/// ```",
    ],
)
def test_doc_fences_fail_closed(repository: Path, source: str) -> None:
    """Encoded tokens, shorter fences, and empty hidden lines cannot bypass policy."""
    with (repository / "src/lib.rs").open("a", encoding="utf-8") as stream:
        _ = stream.write(f"\n{source}\nfn documented() {{}}\n")
    result = check(repository)
    assert result.returncode == 1
    assert "unsafe" in result.stderr or "zero-panic policy" in result.stderr


def test_doc_string_preserves_following_macro_governance(repository: Path) -> None:
    """Decoded doc newlines cannot move a changed macro beyond its diff lines."""
    file = repository / "src/lib.rs"
    original = file.read_text(encoding="utf-8")
    _ = file.write_text(
        r'#[doc = "```\nlet x = 1;\n```"]' + "\n" + original,
        encoding="utf-8",
    )
    _ = git(repository, "add", ".")
    _ = git(repository, "commit", "--quiet", "-m", "documented baseline")
    with file.open("a", encoding="utf-8") as stream:
        _ = stream.write(
            "\nmacro_rules! generated { () => { #[derive(Clone)] struct Item; }; }\n"
        )
    result = check(repository)
    assert result.returncode == 1
    assert "attribute-producing macro outside allowlist" in result.stderr
