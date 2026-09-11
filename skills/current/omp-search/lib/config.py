"""Discover active OMP providers from OMP YAML config files."""

from __future__ import annotations

import os
import re
from pathlib import Path

_KEY_INDENT = 2


def extract_yaml_list(text: str, target_key: str) -> list[str]:
    """Extract list items under providers: -> <target_key>: by indentation."""
    lines = text.split("\n")
    in_section = False
    in_key = False
    items: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_section = False
            in_key = False
            if stripped.startswith("providers:"):
                in_section = True
            continue
        if not in_section:
            continue
        if indent <= _KEY_INDENT and not stripped.startswith("-"):
            in_key = stripped.startswith(f"{target_key}:")
            continue
        if in_key:
            if stripped.startswith("-"):
                item = stripped[1:].strip()
                cleaned_item = re.sub(r"#.*$", "", item).strip()
                cleaned_item = re.sub(r"^['\"]|['\"]$", "", cleaned_item)
                if cleaned_item:
                    items.append(cleaned_item)
            elif indent <= _KEY_INDENT and not stripped.startswith("-"):
                in_key = False

    return items


def _path_exists(file_path: Path) -> bool:
    """Return True when the path exists; never raises."""
    try:
        return file_path.exists()
    except Exception:
        return False


def _read_text_or_empty(file_path: Path) -> str:
    """Read the file as UTF-8 text; return an empty string on failure."""
    try:
        return file_path.read_text(encoding="utf-8")
    except Exception:
        return ""


def discover_active_omp_providers(cwd: str | None = None) -> list[str]:
    """Return the configured active web-search providers, or an empty list."""
    effective_cwd = Path(cwd) if cwd is not None else Path.cwd()
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""

    candidates: list[Path] = []
    omp_config_dir = os.environ.get("OMP_CONFIG_DIR")
    if omp_config_dir:
        candidates.append(Path(omp_config_dir) / "config.yml")
    if home:
        candidates.append(Path(home) / ".omp" / "agent" / "config.yml")
    candidates.append(effective_cwd / ".omp" / "agent" / "config.yml")
    candidates.append(effective_cwd / "harnesses" / "omp" / "agent" / "config.yml")
    if home:
        candidates.append(Path(home) / ".omp" / "config.yml")
    candidates.append(effective_cwd / ".omp" / "config.yml")

    for file_path in candidates:
        if _path_exists(file_path):
            content = _read_text_or_empty(file_path)
            if content:
                order = extract_yaml_list(content, "webSearchOrder")
                exclude = set(extract_yaml_list(content, "webSearchExclude"))
                active = [p for p in order if p not in exclude]
                if active:
                    return active

    return []
