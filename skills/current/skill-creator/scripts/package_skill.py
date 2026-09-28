#!/usr/bin/env -S uv run --script
# Copyright (c) 2026 agents-sync. SPDX-License-Identifier: AGPL-3.0-or-later
# /// script
# requires-python = ">=3.14"
# dependencies = ["PyYAML>=6.0"]
# ///
"""Skill Packager - Creates a distributable .skill file of a skill folder.

Follows the packaging specification from packaging.md:
- .skill files are zip archives containing the skill folder
- Excludes common development artifacts (.git, __pycache__, etc.)
- Excludes the evals/ directory at skill root (packaged separately)
- Validates the skill folder before packaging
"""

import fnmatch
import io
import sys
import zipfile
from pathlib import Path
from typing import Final

from scripts.quick_validate import validate_skill

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if isinstance(sys.stderr, io.TextIOWrapper):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
# Patterns to exclude when packaging skills.
EXCLUDE_DIRS: Final[set[str]] = {"__pycache__", "node_modules"}
EXCLUDE_GLOBS: Final[set[str]] = {"*.pyc"}
EXCLUDE_FILES: Final[set[str]] = {".DS_Store"}
# Directories excluded only at the skill root (not when nested deeper).
ROOT_EXCLUDE_DIRS: Final[set[str]] = {"evals"}


def should_exclude(rel_path: Path) -> bool:
    """Check if a path should be excluded from packaging."""
    parts = rel_path.parts
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    # rel_path is relative to skill_path.parent, so parts[0] is the skill
    # folder name and parts[1] (if present) is the first subdir.
    if len(parts) > 1 and parts[1] in ROOT_EXCLUDE_DIRS:
        return True
    name = rel_path.name
    if name in EXCLUDE_FILES:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_GLOBS)


def package_skill(
    skill_path: str | Path, output_dir: str | Path | None = None
) -> Path | None:
    """Package a skill folder into a .skill file.

    Args:
        skill_path: Path to the skill folder.
        output_dir: Optional output directory for the .skill file
            (defaults to current directory).

    Returns:
        Path to the created .skill file, or None if error.

    """
    skill_dir = Path(skill_path).resolve()

    # Validate skill folder exists
    if not skill_dir.exists():
        print(f"❌ Error: Skill folder not found: {skill_dir}")
        return None

    if not skill_dir.is_dir():
        print(f"❌ Error: Path is not a directory: {skill_dir}")
        return None

    # Validate SKILL.md exists
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        print(f"❌ Error: SKILL.md not found in {skill_dir}")
        return None

    # Run validation before packaging
    print("🔍 Validating skill...")
    valid, message = validate_skill(skill_dir)
    if not valid:
        print(f"❌ Validation failed: {message}")
        print("   Please fix the validation errors before packaging.")
        return None
    print(f"✅ {message}\n")

    # Determine output location
    skill_name = skill_dir.name
    if output_dir:
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = Path.cwd()

    skill_filename = output_path / f"{skill_name}.skill"

    # Create the .skill file (zip format)
    try:
        with zipfile.ZipFile(skill_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Walk through the skill directory, excluding build artifacts
            for file_path in skill_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                arcname = file_path.relative_to(skill_dir.parent)
                if should_exclude(arcname):
                    print(f"  Skipped: {arcname}")
                    continue
                zipf.write(file_path, arcname)
                print(f"  Added: {arcname}")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as e:
        print(f"❌ Error creating .skill file: {e}")
        return None

    print(f"\n✅ Successfully packaged skill to: {skill_filename}")
    return skill_filename


_MIN_ARGV_LEN: Final[int] = 2
_PACKAGE_CLI: Final[str] = "uv run --script <skill-dir>/scripts/cli.py package"


def main() -> None:
    """Package a skill from command-line arguments."""
    if len(sys.argv) < _MIN_ARGV_LEN:
        print(f"Usage: {_PACKAGE_CLI} <path/to/skill-folder> [output-directory]")
        print("\nExample:")
        print(f"  {_PACKAGE_CLI} skills/public/my-skill")
        print(f"  {_PACKAGE_CLI} skills/public/my-skill ./dist")
        sys.exit(1)

    skill_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > _MIN_ARGV_LEN else None

    print(f"📦 Packaging skill: {skill_path}")
    if output_dir:
        print(f"   Output directory: {output_dir}")
    print()

    result = package_skill(skill_path, output_dir)
    sys.exit(0 if result is not None else 1)


if __name__ == "__main__":
    main()
