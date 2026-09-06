"""Unit tests for git commit parsing and extraction."""

import subprocess
from pathlib import Path

from git_extractor import (
    extract_commits_in_range,
    get_diff_stat,
    parse_commit_record,
)


def test_parse_commit_record():
    record = (
        "1234567890abcdef\x00"
        "1234567\x00"
        "Alice Smith\x00"
        "alice@example.com\x00"
        "2026-09-06\x00"
        "feat(core)!: redesign plugin engine (#42)\x00"
        "BREAKING CHANGE: changes signature\x00"
    )
    commit = parse_commit_record(record, Path())
    assert commit is not None
    assert commit.commit_hash == "1234567890abcdef"
    assert commit.short_hash == "1234567"
    assert commit.author_name == "Alice Smith"
    assert commit.subject == "feat(core)!: redesign plugin engine (#42)"
    assert commit.category == "Breaking Changes"
    assert commit.pr_number == 42
    assert commit.is_bot is False
    assert commit.is_revert is False


def test_parse_bot_and_revert_commit():
    record = (
        "abcdef1234567890\x00"
        "abcdef1\x00"
        "dependabot[bot]\x00"
        "dependabot[bot]@users.noreply.github.com\x00"
        "2026-09-06\x00"
        'Revert "feat: breaking experimental flag"\x00'
        "\x00"
    )
    commit = parse_commit_record(record, Path())
    assert commit is not None
    assert commit.is_bot is True
    assert commit.is_revert is True


def test_git_repo_extraction(tmp_path: Path):
    # Initialize a temporary git repository
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Base commit
    f0 = tmp_path / "base.txt"
    f0.write_text("base", encoding="utf-8")
    subprocess.run(
        ["git", "add", "base.txt"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: base"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Commit 1
    f1 = tmp_path / "file1.txt"
    f1.write_text("initial content", encoding="utf-8")
    subprocess.run(
        ["git", "add", "file1.txt"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "feat: initial commit (#1)"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    # Commit 2
    f2 = tmp_path / "file2.txt"
    f2.write_text("another feature", encoding="utf-8")
    subprocess.run(
        ["git", "add", "file2.txt"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "fix(core): fix buffer overflow (#2)"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    commits = extract_commits_in_range("HEAD~2..HEAD", tmp_path)
    assert len(commits) == 2
    assert commits[0].subject == "fix(core): fix buffer overflow (#2)"
    assert commits[0].category == "Fixed"
    assert commits[0].pr_number == 2

    stat = get_diff_stat(tmp_path, range_spec="HEAD~1..HEAD")
    assert "file2.txt" in stat
