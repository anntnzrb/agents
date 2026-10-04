#!/usr/bin/env -S uv run --script
# Copyright (c) 2026
# /// script
# requires-python = ">=3.14"
# dependencies = ["PyYAML>=6.0"]
# ///
"""Quick validation script for skills - minimal version."""

import re
import sys
from pathlib import Path
from typing import Final

from scripts.frontmatter import read_frontmatter

MAX_DESCRIPTION_CHARS: Final[int] = 120
MAX_NAME_CHARS: Final[int] = 64
MAX_COMPATIBILITY_CHARS: Final[int] = 500
EXPECTED_ARG_COUNT: Final[int] = 2

ALLOWED_PROPERTIES: Final[set[str]] = {
    "name",
    "description",
    "license",
    "metadata",
    "compatibility",
    "disable-model-invocation",
}


def _load_frontmatter(skill_md: Path) -> tuple[bool, str | dict[str, object]]:
    """Load frontmatter and render validation errors."""
    if not skill_md.exists():
        return False, "SKILL.md not found"
    result = read_frontmatter(skill_md.read_text(encoding="utf-8"))
    if result.metadata is None:
        return False, result.error or "Invalid frontmatter format"
    return True, result.metadata


def _validate_name(name: object) -> tuple[bool, str]:
    """Validate the skill name from frontmatter."""
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}"
    name = name.strip()
    if not name:
        return False, "Name must not be empty"
    if not re.match(r"^[a-z0-9-]+$", name):
        return (
            False,
            (
                f"Name '{name}' should be kebab-case "
                "(lowercase letters, digits, and hyphens only)"
            ),
        )
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return (
            False,
            (
                f"Name '{name}' cannot start/end with hyphen "
                "or contain consecutive hyphens"
            ),
        )
    if len(name) > MAX_NAME_CHARS:
        return (
            False,
            (
                f"Name is too long ({len(name)} characters). "
                f"Maximum is {MAX_NAME_CHARS} characters."
            ),
        )
    return True, ""


def _validate_description(description: object) -> tuple[bool, str]:
    """Validate the skill description from frontmatter."""
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}"
    description = description.strip()
    if not description:
        return False, "Description must contain a nonempty trigger contract"
    if "<" in description or ">" in description:
        return False, "Description cannot contain angle brackets (< or >)"
    if len(description) > MAX_DESCRIPTION_CHARS:
        return (
            False,
            (
                f"Description is too long ({len(description)} characters). "
                f"Maximum is {MAX_DESCRIPTION_CHARS} characters."
            ),
        )
    if not re.match(r"^Use (?:when|for|before) \S", description):
        return (
            False,
            (
                "Description must start with 'Use when', 'Use for', or 'Use before' "
                "followed by trigger wording, not a synopsis"
            ),
        )
    return True, ""


def _validate_compatibility(compatibility: object) -> tuple[bool, str]:
    """Validate the optional compatibility field."""
    if not compatibility:
        return True, ""
    if not isinstance(compatibility, str):
        return (
            False,
            (f"Compatibility must be a string, got {type(compatibility).__name__}"),
        )
    if len(compatibility) > MAX_COMPATIBILITY_CHARS:
        return (
            False,
            (
                f"Compatibility is too long ({len(compatibility)} characters). "
                f"Maximum is {MAX_COMPATIBILITY_CHARS} characters."
            ),
        )
    return True, ""


def validate_skill(skill_path: str | Path) -> tuple[bool, str]:
    """Validate a skill directory, returning (is_valid, message)."""
    skill_md = Path(skill_path) / "SKILL.md"
    loaded, frontmatter = _load_frontmatter(skill_md)
    if not loaded or not isinstance(frontmatter, dict):
        return False, str(frontmatter)
    unexpected = set(frontmatter.keys()) - ALLOWED_PROPERTIES
    if unexpected:
        keys = ", ".join(sorted(unexpected))
        return (
            False,
            (
                f"Unexpected key(s) in SKILL.md frontmatter: {keys}. "
                f"Allowed properties are: {', '.join(sorted(ALLOWED_PROPERTIES))}"
            ),
        )
    if "name" not in frontmatter:
        return False, "Missing 'name' in frontmatter"
    if "description" not in frontmatter:
        return False, "Missing 'description' in frontmatter"

    checks = (
        _validate_name(frontmatter.get("name", "")),
        _validate_description(frontmatter.get("description", "")),
        _validate_compatibility(frontmatter.get("compatibility", "")),
    )
    for ok, message in checks:
        if not ok:
            return False, message

    directory_name = skill_md.parent.resolve().name
    if frontmatter["name"] != directory_name:
        return False, f"Name must match skill directory '{directory_name}'"

    return True, "Skill is valid!"


if __name__ == "__main__":
    if len(sys.argv) != EXPECTED_ARG_COUNT:
        print("Usage: uv run --script scripts/cli.py quick-validate <skill_directory>")
        sys.exit(1)

    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)
