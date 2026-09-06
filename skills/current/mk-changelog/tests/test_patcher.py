"""Unit tests for changelog patching and deduplication."""

from pathlib import Path

from patcher import (
    deduplicate_entries,
    patch_changelog_content,
    patch_changelog_file,
)


def test_deduplicate_entries():
    existing = ["Added fast indexing", "Fixed crash on startup"]
    new_items = [
        "added fast indexing.",
        "Added background sync",
        "Fixed crash on startup",
    ]

    merged = deduplicate_entries(existing, new_items)
    assert merged == [
        "Added fast indexing",
        "Fixed crash on startup",
        "Added background sync",
    ]


def test_patch_changelog_existing_unreleased():
    original = """# Changelog

## [Unreleased]

### Added
- Existing feature A

## [1.0.0] - 2026-01-01

### Added
- Initial release
"""
    new_entries = {
        "Added": ["Existing feature a.", "New feature B"],
        "Fixed": ["Fixed memory leak"],
    }
    patched, changed = patch_changelog_content(original, new_entries)
    assert changed is True
    assert "### Added" in patched
    assert "- Existing feature A" in patched
    assert "- New feature B" in patched
    assert "### Fixed" in patched
    assert "- Fixed memory leak" in patched
    assert "## [1.0.0] - 2026-01-01" in patched


def test_patch_changelog_missing_unreleased():
    original = """# Changelog

## [1.0.0] - 2026-01-01

### Added
- Initial release
"""
    new_entries = {"Fixed": ["Fixed crash on exit"]}
    patched, changed = patch_changelog_content(original, new_entries)
    assert changed is True
    assert "## [Unreleased]" in patched
    assert "### Fixed" in patched
    assert "- Fixed crash on exit" in patched
    assert patched.index("## [Unreleased]") < patched.index("## [1.0.0]")


def test_patch_changelog_file_roundtrip(tmp_path: Path):
    cl_path = tmp_path / "CHANGELOG.md"
    new_entries = {"Added": ["Brand new feature"]}

    # Create from scratch
    changed1 = patch_changelog_file(cl_path, new_entries)
    assert changed1 is True
    assert cl_path.is_file()
    content1 = cl_path.read_text(encoding="utf-8")
    assert "## [Unreleased]" in content1
    assert "- Brand new feature" in content1

    # Idempotent second patch with same entry
    changed2 = patch_changelog_file(cl_path, {"Added": ["brand new feature."]})
    assert changed2 is False
