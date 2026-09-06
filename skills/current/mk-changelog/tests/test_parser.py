"""Unit tests for changelog parsing and formatting."""

from parser import (
    format_entries_markdown,
    parse_unreleased_section,
)

SAMPLE_CHANGELOG: str = """# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Implemented user profile endpoint
- Added OAuth2 support

### Fixed
- Fixed token expiration bug

## [1.0.0] - 2026-01-01

### Added
- Initial release
"""


def test_parse_unreleased_section():
    parsed = parse_unreleased_section(SAMPLE_CHANGELOG)
    assert parsed.unreleased_found is True
    assert "Added" in parsed.entries
    assert "Fixed" in parsed.entries
    assert len(parsed.entries["Added"]) == 2
    assert "Implemented user profile endpoint" in parsed.entries["Added"]
    assert "Fixed token expiration bug" in parsed.entries["Fixed"]


def test_parse_missing_unreleased():
    content = """# Changelog
## [1.0.0] - 2026-01-01
### Added
- Initial
"""
    parsed = parse_unreleased_section(content)
    assert parsed.unreleased_found is False
    assert parsed.entries == {}


def test_format_entries_markdown():
    entries = {
        "Fixed": ["Fixed regression in auth"],
        "Added": ["Added new --json flag."],
        "Breaking Changes": ["Removed legacy v1 API"],
    }
    formatted = format_entries_markdown(entries, include_header=True)
    expected_lines = [
        "## [Unreleased]",
        "",
        "### Breaking Changes",
        "- Removed legacy v1 API",
        "",
        "### Added",
        "- Added new --json flag",
        "",
        "### Fixed",
        "- Fixed regression in auth",
    ]
    assert formatted == "\n".join(expected_lines)
