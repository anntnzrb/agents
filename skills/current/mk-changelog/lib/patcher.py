"""Idempotent changelog patching engine."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from models import CATEGORIES
from parser import (
    VERSION_HEADER_PATTERN,
    format_entries_markdown,
    parse_unreleased_section,
)

DEFAULT_CHANGELOG_HEADER: str = """# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
"""


def deduplicate_entries(
    existing_items: Sequence[str],
    new_items: Sequence[str],
) -> list[str]:
    """Merge and deduplicate items preserving order without case-insensitive duplicates."""
    seen: set[str] = set()
    result: list[str] = []

    for item in existing_items:
        norm = item.strip().rstrip(".").lower()
        if norm and norm not in seen:
            seen.add(norm)
            result.append(item.strip().rstrip("."))

    for item in new_items:
        norm = item.strip().rstrip(".").lower()
        if norm and norm not in seen:
            seen.add(norm)
            result.append(item.strip().rstrip("."))

    return result


def patch_changelog_content(
    original_content: str,
    new_entries: Mapping[str, Sequence[str]],
) -> tuple[str, bool]:
    """Patch unreleased section in changelog content.

    Returns (new_content, changed).
    """
    has_new_entries = any(items for items in new_entries.values() if items)
    if not original_content.strip():
        if not has_new_entries:
            return "", False
        # Create new changelog
        formatted = format_entries_markdown(new_entries, include_header=True)
        new_content = f"{DEFAULT_CHANGELOG_HEADER.strip()}\n\n{formatted}\n"
        return new_content, True

    parsed = parse_unreleased_section(original_content)
    if not has_new_entries and not parsed.unreleased_found:
        return original_content, False
    lines = original_content.splitlines()

    # Merge categories
    merged_entries: dict[str, list[str]] = {}

    # Standard order first
    for cat in CATEGORIES:
        existing_list = parsed.entries.get(cat, [])
        new_list = new_entries.get(cat, [])
        if existing_list or new_list:
            merged = deduplicate_entries(existing_list, new_list)
            if merged:
                merged_entries[cat] = merged

    # Any other categories in either
    all_other_cats = set(parsed.entries.keys()).union(new_entries.keys()) - set(
        CATEGORIES
    )
    for cat in sorted(all_other_cats):
        existing_list = parsed.entries.get(cat, [])
        new_list = new_entries.get(cat, [])
        merged = deduplicate_entries(existing_list, new_list)
        if merged:
            merged_entries[cat] = merged

    formatted_unreleased = format_entries_markdown(merged_entries, include_header=True)

    if parsed.unreleased_found:
        # Replace the entire [Unreleased] block from start_line to end_line
        before = lines[: parsed.start_line]
        after = lines[parsed.end_line :]

        # Strip trailing blank lines from 'before' and leading blank lines from 'after'
        while before and not before[-1].strip():
            before.pop()
        while after and not after[0].strip():
            after.pop(0)

        assembled_parts: list[str] = []
        if before:
            assembled_parts.append("\n".join(before))
        assembled_parts.append(formatted_unreleased)
        if after:
            assembled_parts.append("\n".join(after))

        new_content = "\n\n".join(assembled_parts) + "\n"
        changed = new_content != original_content
        return new_content, changed

    # [Unreleased] not found: find insertion point before first release header
    insert_idx = -1
    for idx, line in enumerate(lines):
        if VERSION_HEADER_PATTERN.match(line.strip()):
            insert_idx = idx
            break

    if insert_idx != -1:
        before = lines[:insert_idx]
        after = lines[insert_idx:]
        while before and not before[-1].strip():
            before.pop()
        assembled_parts = [
            "\n".join(before),
            formatted_unreleased,
            "\n".join(after),
        ]
        new_content = "\n\n".join(assembled_parts) + "\n"
        return new_content, True

    # No version headers found; append to end
    assembled = original_content.rstrip() + "\n\n" + formatted_unreleased + "\n"
    return assembled, True


def patch_changelog_file(
    file_path: Path,
    new_entries: Mapping[str, Sequence[str]],
) -> bool:
    """Patch an existing changelog file or create one if it does not exist."""
    original_content = (
        file_path.read_text(encoding="utf-8") if file_path.is_file() else ""
    )
    new_content, changed = patch_changelog_content(original_content, new_entries)

    if changed:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(new_content, encoding="utf-8")

    return changed
