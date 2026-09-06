"""Monorepo and single-package changelog boundary detection."""

from collections.abc import Sequence
from pathlib import Path

from models import BoundaryInfo

CHANGELOG_FILENAME: str = "CHANGELOG.md"


def find_nearest_changelog(file_path: str, repo_root: Path) -> Path | None:
    """Find the nearest CHANGELOG.md walking up from file_path to repo_root."""
    resolved_root = repo_root.resolve()
    target_path = (resolved_root / file_path).resolve()
    current_dir = (
        target_path.parent
        if target_path.is_file() or not target_path.exists()
        else target_path
    )

    while True:
        candidate = current_dir / CHANGELOG_FILENAME
        if candidate.is_file():
            return candidate

        if current_dir == resolved_root:
            break
        if current_dir.parent == current_dir:
            break
        current_dir = current_dir.parent

    # Check repository root as fallback
    root_candidate = resolved_root / CHANGELOG_FILENAME
    if root_candidate.is_file():
        return root_candidate

    return None


def detect_changelog_boundaries(
    files: Sequence[str],
    repo_root: Path,
) -> list[BoundaryInfo]:
    """Group changed files by their owning nearest CHANGELOG.md."""
    resolved_root = repo_root.resolve()
    boundaries_map: dict[str, list[str]] = {}

    for file_str in files:
        if file_str.lower().endswith("changelog.md"):
            continue

        nearest = find_nearest_changelog(file_str, resolved_root)
        cl_path = (
            str(nearest.relative_to(resolved_root)) if nearest else CHANGELOG_FILENAME
        )
        if cl_path not in boundaries_map:
            boundaries_map[cl_path] = []
        boundaries_map[cl_path].append(file_str)

    results: list[BoundaryInfo] = []
    for cl_rel, flist in boundaries_map.items():
        abs_path = (resolved_root / cl_rel).resolve()
        results.append(
            BoundaryInfo(
                changelog_path=str(abs_path),
                relative_path=cl_rel,
                files=flist,
            )
        )

    return results
