"""Unit tests for changelog boundary detection."""

from pathlib import Path

from boundary_detector import detect_changelog_boundaries, find_nearest_changelog


def test_find_nearest_changelog_monorepo(tmp_path: Path):
    root_cl = tmp_path / "CHANGELOG.md"
    root_cl.write_text("# Root Changelog\n", encoding="utf-8")

    pkg_a = tmp_path / "packages" / "pkg-a"
    pkg_a.mkdir(parents=True)
    pkg_a_cl = pkg_a / "CHANGELOG.md"
    pkg_a_cl.write_text("# Package A Changelog\n", encoding="utf-8")

    pkg_b = tmp_path / "packages" / "pkg-b"
    pkg_b.mkdir(parents=True)

    # File inside pkg-a resolves to pkg-a CHANGELOG.md
    file_a = "packages/pkg-a/src/index.ts"
    nearest_a = find_nearest_changelog(file_a, tmp_path)
    assert nearest_a == pkg_a_cl

    # File inside pkg-b falls back to root CHANGELOG.md
    file_b = "packages/pkg-b/src/index.ts"
    nearest_b = find_nearest_changelog(file_b, tmp_path)
    assert nearest_b == root_cl


def test_detect_changelog_boundaries(tmp_path: Path):
    root_cl = tmp_path / "CHANGELOG.md"
    root_cl.write_text("# Root Changelog\n", encoding="utf-8")

    pkg_a = tmp_path / "packages" / "core"
    pkg_a.mkdir(parents=True)
    pkg_a_cl = pkg_a / "CHANGELOG.md"
    pkg_a_cl.write_text("# Core Changelog\n", encoding="utf-8")

    files = [
        "packages/core/src/feature.ts",
        "packages/core/src/util.ts",
        "docs/readme.md",
    ]

    boundaries = detect_changelog_boundaries(files, tmp_path)
    rel_paths = {b.relative_path for b in boundaries}
    assert "packages/core/CHANGELOG.md" in rel_paths
    assert "CHANGELOG.md" in rel_paths

    for b in boundaries:
        if b.relative_path == "packages/core/CHANGELOG.md":
            assert len(b.files) == 2
        elif b.relative_path == "CHANGELOG.md":
            assert b.files == ["docs/readme.md"]
