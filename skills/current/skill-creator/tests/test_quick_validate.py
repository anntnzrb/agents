# Copyright (c) 2026
"""Executable contracts for the skill-creator quick validator."""

from __future__ import annotations

import subprocess
from pathlib import Path

SKILL: Path = Path(__file__).resolve().parents[1]
CLI: Path = SKILL / "scripts" / "cli.py"

_VALID_FRONTMATTER = """---
name: fixture-skill
description: Fixture skill for validator contract tests.
---
"""


def write_skill(root: Path, frontmatter: str | None) -> Path:
    """Create a fixture skill directory with the given frontmatter."""
    root.mkdir(parents=True, exist_ok=True)
    if frontmatter is not None:
        _ = (root / "SKILL.md").write_text(
            f"{frontmatter}\n# Fixture\n", encoding="utf-8"
        )
    return root


def run_validate(target: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the quick-validate dispatcher entry point on one directory."""
    return subprocess.run(
        ["uv", "run", "--quiet", "--script", str(CLI), "quick-validate", str(target)],
        cwd=SKILL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_valid_skill_passes(tmp_path: Path) -> None:
    """Valid fixture skill passes quick validation."""
    result = run_validate(write_skill(tmp_path / "ok", _VALID_FRONTMATTER))
    assert result.returncode == 0
    assert "Skill is valid!" in result.stdout


def test_missing_skill_md_fails(tmp_path: Path) -> None:
    """Missing SKILL.md fails quick validation."""
    target = tmp_path / "empty"
    target.mkdir(parents=True, exist_ok=True)
    result = run_validate(target)
    assert result.returncode == 1
    assert "SKILL.md not found" in result.stdout


def test_missing_frontmatter_fails(tmp_path: Path) -> None:
    """Missing frontmatter fails quick validation."""
    result = run_validate(write_skill(tmp_path / "bare", "# No frontmatter\n"))
    assert result.returncode == 1


def test_long_description_fails(tmp_path: Path) -> None:
    """Overlong description fails quick validation."""
    frontmatter = "---\nname: fixture-skill\ndescription: " + "x" * 121 + "\n---\n"
    result = run_validate(write_skill(tmp_path / "long", frontmatter))
    assert result.returncode == 1
    assert "too long" in result.stdout


def test_bad_name_fails(tmp_path: Path) -> None:
    """Non-kebab-case name fails quick validation."""
    frontmatter = "---\nname: Not_Kebab\ndescription: Fixture.\n---\n"
    result = run_validate(write_skill(tmp_path / "name", frontmatter))
    assert result.returncode == 1
    assert "kebab-case" in result.stdout


def test_unexpected_key_fails(tmp_path: Path) -> None:
    """Unexpected frontmatter key fails quick validation."""
    frontmatter = _VALID_FRONTMATTER.replace("---\n", "---\nbogus: 1\n", 1)
    result = run_validate(write_skill(tmp_path / "key", frontmatter))
    assert result.returncode == 1
    assert "Unexpected key" in result.stdout
