"""Small dotenv loader with explicit, testable precedence."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

ENV_FILE_VAR = "GAME_DEALS_ENV_FILE"
SKILLS_DIR_VAR = "SKILLS_DIR"


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse basic dotenv syntax without interpolation or code execution."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, IsADirectoryError):
        return values

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key or not key.replace("_", "a").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def env_candidates(
    *,
    environ: Mapping[str, str],
    skill_dir: Path,
    cwd: Path,
) -> list[Path]:
    """Return dotenv files from highest to lowest precedence."""
    candidates: list[Path] = []
    explicit = environ.get(ENV_FILE_VAR)
    if explicit:
        candidates.append(Path(explicit).expanduser())

    candidates.append(skill_dir / ".env")

    skills_dir = environ.get(SKILLS_DIR_VAR)
    if skills_dir:
        root = Path(skills_dir).expanduser()
        candidates.extend((root / "game-deals-live" / ".env", root / ".env"))

    candidates.extend(
        parent / "skills" / "game-deals-live" / ".env" for parent in (cwd, *cwd.parents)
    )

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved not in seen:
            unique.append(candidate)
            seen.add(resolved)
    return unique


def load_environment(
    *,
    environ: Mapping[str, str] | None = None,
    skill_dir: Path,
    cwd: Path | None = None,
) -> dict[str, str]:
    """Merge process and dotenv values; earlier sources always win."""
    source = dict(os.environ if environ is None else environ)
    merged = dict(source)
    for path in env_candidates(
        environ=source,
        skill_dir=skill_dir,
        cwd=Path.cwd() if cwd is None else cwd,
    ):
        for key, value in parse_env_file(path).items():
            merged.setdefault(key, value)
    return merged
