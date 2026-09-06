"""Keep a Changelog parser and markdown formatter."""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from models import CATEGORIES, ExistingEntries

UNRELEASED_PATTERN: re.Pattern[str] = re.compile(
    r"^##\s+\[?Unreleased\]?",
    re.IGNORECASE,
)
SECTION_PATTERN: re.Pattern[str] = re.compile(r"^###\s+(.*)$")
VERSION_HEADER_PATTERN: re.Pattern[str] = re.compile(r"^##\s+\[?v?\d+")


def parse_unreleased_section(content: str) -> ExistingEntries:
    """Parse the ## [Unreleased] section of a CHANGELOG.md."""
    lines = content.splitlines()
    start_index = -1

    for idx, line in enumerate(lines):
        if UNRELEASED_PATTERN.match(line.strip()):
            start_index = idx
            break

    if start_index == -1:
        return ExistingEntries(
            unreleased_found=False,
            start_line=0,
            end_line=0,
            entries={},
        )

    end_index = len(lines)
    for idx in range(start_index + 1, len(lines)):
        line = lines[idx]
        if line.startswith("## ") and (
            VERSION_HEADER_PATTERN.match(line) or UNRELEASED_PATTERN.match(line)
        ):
            end_index = idx
            break

    section_lines = lines[start_index + 1 : end_index]
    entries: dict[str, list[str]] = {}
    current_category: str | None = None

    for line in section_lines:
        stripped = line.strip()
        if match := SECTION_PATTERN.match(stripped):
            cat_name = match.group(1).strip()
            current_category = cat_name
            if cat_name not in entries:
                entries[cat_name] = []
            continue

        if current_category and stripped.startswith(("- ", "* ")):
            bullet = stripped[2:].strip()
            if bullet:
                entries[current_category].append(bullet)

    return ExistingEntries(
        unreleased_found=True,
        start_line=start_index,
        end_line=end_index,
        entries=entries,
    )


def parse_changelog_file(file_path: Path) -> ExistingEntries:
    """Read and parse existing changelog file if present."""
    if not file_path.is_file():
        return ExistingEntries(
            unreleased_found=False,
            start_line=0,
            end_line=0,
            entries={},
        )
    content = file_path.read_text(encoding="utf-8")
    return parse_unreleased_section(content)


def format_entries_markdown(
    entries: Mapping[str, Sequence[str]],
    include_header: bool = False,
) -> str:
    """Format structured entries mapping into standard Keep a Changelog markdown."""
    lines: list[str] = []
    if include_header:
        lines.append("## [Unreleased]")
        lines.append("")

    # Output recognized categories in standardized canonical order
    for cat in CATEGORIES:
        if entries.get(cat):
            lines.append(f"### {cat}")
            for item in entries[cat]:
                clean_item = item.strip().rstrip(".")
                lines.append(f"- {clean_item}")
            lines.append("")

    # Output any extra categories not in canonical list
    for cat, items in entries.items():
        if cat not in CATEGORIES and items:
            lines.append(f"### {cat}")
            for item in items:
                clean_item = item.strip().rstrip(".")
                lines.append(f"- {clean_item}")
            lines.append("")

    return "\n".join(lines).strip()
