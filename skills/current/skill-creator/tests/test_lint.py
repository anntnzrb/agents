# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
"""Executable contracts for the skill-creator mechanical lint."""

import os
import subprocess
from pathlib import Path
from typing import Final

import pytest

from scripts.lint_skills import READS_TABLE_MISSING, Finding, lint_skill

SKILL: Final[Path] = Path(__file__).resolve().parents[1]
CLI: Final[Path] = SKILL / "scripts" / "cli.py"
EN_DASH: Final[str] = "\N{EN DASH}"
EM_DASH: Final[str] = "\N{EM DASH}"
EXIT_USAGE: Final[int] = 2

_FRONTMATTER: Final[str] = (
    "---\n"
    "name: fixture\n"
    "description: Use when checking fixtures.\n"
    "license: AGPL-3.0-or-later\n"
    "---\n"
)
_READS_TABLE: Final[str] = (
    "## Required follow-up reads\n\n"
    "| Need | Read | When |\n"
    "|---|---|---|\n"
    "| Usage | `references/usage.md` | Always |\n"
)


def write(root: Path, rel: str, text: str) -> Path:
    """Write one fixture file below root, creating parents."""
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    _ = target.write_text(text, encoding="utf-8")
    return target


def make_skill(root: Path, body: str = "# Fixture\n") -> Path:
    """Create a clean minimal skill with no bundled docs."""
    _ = write(root, "SKILL.md", _FRONTMATTER + body)
    return root


def messages(findings: list[Finding]) -> list[str]:
    """Render findings exactly as the CLI prints them, relative to nothing."""
    return [f"{f.path.name}:{f.line}: {f.message}" for f in findings]


def run_lint(*args: str, cwd: Path = SKILL) -> subprocess.CompletedProcess[str]:
    """Invoke the lint dispatcher entry point."""
    return subprocess.run(
        ["uv", "run", "--quiet", "--script", str(CLI), "lint", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_clean_skill_has_no_findings(tmp_path: Path) -> None:
    """A minimal compliant skill passes."""
    assert lint_skill(make_skill(tmp_path / "ok")) == []


@pytest.mark.parametrize("dash", [EN_DASH, EM_DASH])
def test_dash_in_prose_is_reported_with_its_line(tmp_path: Path, dash: str) -> None:
    """En and em dashes in Markdown prose are findings."""
    skill = make_skill(tmp_path / "s", f"# Fixture\n\nOne {dash} two.\n")
    findings = lint_skill(skill)
    assert [(f.path.name, f.line) for f in findings] == [("SKILL.md", 8)]
    assert "U+20" in findings[0].message


def test_dash_in_frontmatter_description_is_reported(tmp_path: Path) -> None:
    """The description is model-facing prose too."""
    skill = tmp_path / "s"
    _ = write(
        skill,
        "SKILL.md",
        _FRONTMATTER.replace("checking fixtures", f"a {EM_DASH} b"),
    )
    assert [f.line for f in lint_skill(skill)] == [3]


def test_dash_in_code_is_ignored(tmp_path: Path) -> None:
    """Fenced blocks, tilde fences, and inline code may hold any character."""
    body = (
        "# Fixture\n\n"
        f"Run `a {EM_DASH} b` or ``x ` {EN_DASH} y`` here.\n\n"
        f"```text\n{EM_DASH}\n```\n\n"
        f"  ~~~~\n  {EN_DASH}\n  ```\n  ~~~~\n"
    )
    assert lint_skill(make_skill(tmp_path / "s", body)) == []


def test_dash_in_reference_doc_is_reported(tmp_path: Path) -> None:
    """Every Markdown file in the skill is checked, not only SKILL.md."""
    skill = make_skill(tmp_path / "s", "# Fixture\n\n" + _READS_TABLE)
    _ = write(skill, "references/usage.md", f"# Usage\n\nA {EN_DASH} b.\n")
    assert messages(lint_skill(skill)) == [
        "usage.md:3: U+2013 en dash in Markdown prose"
    ]


def test_dash_in_non_markdown_file_is_ignored(tmp_path: Path) -> None:
    """Code and fixtures are never altered to satisfy the prose rule."""
    skill = make_skill(tmp_path / "s")
    _ = write(skill, "scripts/cli.py", f'SEP = "{EM_DASH}"\n')
    assert lint_skill(skill) == []


def test_trailing_whitespace_is_reported_in_any_text_file(tmp_path: Path) -> None:
    """Trailing spaces and tabs are reported like git diff --check."""
    skill = make_skill(tmp_path / "s", "# Fixture \n")
    _ = write(skill, "scripts/cli.py", "x = 1\t\n")
    assert sorted(messages(lint_skill(skill))) == [
        "SKILL.md:6: trailing whitespace",
        "cli.py:1: trailing whitespace",
    ]


def test_space_before_tab_in_indent_is_reported(tmp_path: Path) -> None:
    """Git reports a space before a tab in the indent."""
    skill = make_skill(tmp_path / "s")
    _ = write(skill, "data.txt", "ok\n \tbad\n")
    assert messages(lint_skill(skill)) == ["data.txt:2: space before tab in indent"]


def test_end_of_file_needs_exactly_one_newline(tmp_path: Path) -> None:
    """A missing final newline and blank lines at EOF are both findings."""
    skill = make_skill(tmp_path / "s")
    _ = write(skill, "missing.txt", "a\nb")
    _ = write(skill, "blank.txt", "a\n\n\n")
    _ = write(skill, "empty.txt", "")
    assert sorted(messages(lint_skill(skill))) == [
        "blank.txt:2: blank line at end of file",
        "missing.txt:2: no newline at end of file",
    ]


def test_binary_files_are_skipped(tmp_path: Path) -> None:
    """Binary content is not text and has no whitespace rules."""
    skill = make_skill(tmp_path / "s")
    _ = (skill / "image.bin").write_bytes(b"\x00\x01 \n\xff")
    assert lint_skill(skill) == []


def test_missing_license_is_reported(tmp_path: Path) -> None:
    """Every SKILL.md declares the repository license."""
    skill = tmp_path / "s"
    _ = write(skill, "SKILL.md", _FRONTMATTER.replace("AGPL-3.0-or-later", "MIT"))
    assert messages(lint_skill(skill)) == [
        "SKILL.md:1: frontmatter lacks license: AGPL-3.0-or-later"
    ]


def test_missing_skill_md_is_reported(tmp_path: Path) -> None:
    """A skill directory without its entrypoint is a finding."""
    skill = tmp_path / "s"
    skill.mkdir()
    assert messages(lint_skill(skill)) == ["SKILL.md:1: SKILL.md not found"]


def test_bundled_docs_require_follow_up_reads_table(tmp_path: Path) -> None:
    """References without a Need/Read/When table are a finding."""
    skill = make_skill(tmp_path / "s")
    _ = write(skill, "agents/grader.md", "# Grader\n")
    assert messages(lint_skill(skill)) == [f"SKILL.md:1: {READS_TABLE_MISSING}"]


def test_follow_up_reads_table_satisfies_bundled_docs(tmp_path: Path) -> None:
    """Compact table syntax without padding is accepted."""
    table = "|Need|Read|When|\n|---|---|---|\n|a|`references/a.md`|b|\n"
    skill = make_skill(tmp_path / "s", "# Fixture\n\n" + table)
    _ = write(skill, "references/a.md", "# A\n")
    assert lint_skill(skill) == []


def test_table_inside_code_fence_does_not_count(tmp_path: Path) -> None:
    """An example table in a code block is not the routing table."""
    skill = make_skill(tmp_path / "s", "# Fixture\n\n```md\n" + _READS_TABLE + "```\n")
    _ = write(skill, "references/usage.md", "# Usage\n")
    assert len(lint_skill(skill)) == 1


def test_notice_is_not_a_bundled_doc(tmp_path: Path) -> None:
    """Attribution files need no routing table."""
    skill = make_skill(tmp_path / "s")
    _ = write(skill, "NOTICE.md", "# NOTICE\n")
    assert lint_skill(skill) == []


def test_skill_md_line_cap_applies_with_bundled_docs(tmp_path: Path) -> None:
    """The 250-line hard cap is enforced when references exist."""
    filler = "".join(f"Line {n}.\n" for n in range(250))
    skill = make_skill(tmp_path / "s", _READS_TABLE + filler)
    _ = write(skill, "references/usage.md", "# Usage\n")
    assert messages(lint_skill(skill)) == [
        "SKILL.md:251: SKILL.md has 260 lines; hard cap is 250"
    ]


def test_skill_md_line_cap_exempts_skills_without_bundled_docs(
    tmp_path: Path,
) -> None:
    """docs/skills.md exempts skills that have no bundled references."""
    filler = "".join(f"Line {n}.\n" for n in range(300))
    assert lint_skill(make_skill(tmp_path / "s", filler)) == []


def test_upstream_requires_notice(tmp_path: Path) -> None:
    """A tracked upstream port preserves upstream notices."""
    skill = make_skill(tmp_path / "s")
    _ = write(skill, "UPSTREAM.json", "{}\n")
    assert messages(lint_skill(skill)) == [
        "UPSTREAM.json:1: UPSTREAM.json exists but NOTICE.md is missing"
    ]
    _ = write(skill, "NOTICE.md", "# NOTICE\n")
    assert lint_skill(skill) == []


def test_cli_exit_codes_and_output_format(tmp_path: Path) -> None:
    """Clean exits 0, findings exit 1 as path:line: message, bad usage exits 2."""
    clean = make_skill(tmp_path / "clean")
    dirty = make_skill(tmp_path / "dirty", "# Fixture \n")
    ok = run_lint(str(clean))
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = run_lint(str(clean), str(dirty))
    assert bad.returncode == 1
    assert f"{dirty / 'SKILL.md'}:6: trailing whitespace" in bad.stdout
    missing = run_lint(str(tmp_path / "nope"))
    assert missing.returncode == EXIT_USAGE
    assert run_lint("--bogus").returncode == EXIT_USAGE


def _git(cwd: Path, *args: str) -> None:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    _ = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Lint Test",
            "-c",
            "user.email=lint@example.test",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        env=env,
    )


def test_whitespace_attribute_is_honored_like_git_diff_check(tmp_path: Path) -> None:
    """Git whitespace attributes exempt verbatim fixtures and patches."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _ = write(
        repo,
        ".gitattributes",
        "s/fixtures/** -whitespace\n*.patch whitespace=-trailing-space\n",
    )
    skill = make_skill(repo / "s")
    _ = write(skill, "fixtures/raw.txt", "a \nb")
    _ = write(skill, "fix.patch", " a \n \tb\n")
    _ = write(skill, "other.txt", "a \n")
    assert sorted(messages(lint_skill(skill))) == [
        "fix.patch:2: space before tab in indent",
        "other.txt:1: trailing whitespace",
    ]


def test_no_arguments_lints_skills_changed_against_origin_main(
    tmp_path: Path,
) -> None:
    """Without arguments, changed and untracked current skills are checked."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _ = make_skill(repo / "skills/current/untouched", "# Old \n")
    _ = make_skill(repo / "skills/current/edited")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert run_lint(cwd=repo).returncode == 0

    _ = write(repo, "skills/current/edited/SKILL.md", _FRONTMATTER + "# New \n")
    _ = make_skill(repo / "skills/current/fresh", f"A {EM_DASH} b.\n")
    _ = make_skill(repo / "skills/legacy/old", "# Old \n")
    result = run_lint(cwd=repo)
    assert result.returncode == 1
    out = result.stdout
    assert "skills/current/edited/SKILL.md:6: trailing whitespace" in out
    assert "skills/current/fresh/SKILL.md:6: U+2014 em dash" in out
    assert "untouched" not in out
    assert "legacy" not in out
