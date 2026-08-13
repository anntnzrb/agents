# Copyright (c) 2026
"""CLI configuration and backend discovery orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .jsonl_backends import discover_jsonl_sessions
from .model import Harness, Record, rank
from .sqlite_backends import discover_sqlite_sessions, validate_sqlite_root

ALL_HARNESSES: tuple[Harness, ...] = ("omp", "pi", "codex", "t3code", "opencode")


class ConfigurationError(ValueError):
    """An invalid explicit CLI configuration."""


@dataclass(frozen=True, slots=True)
class SearchConfig:
    """Validated search configuration."""

    harnesses: tuple[Harness, ...]
    roots: dict[Harness, tuple[Path, ...]]


def _harness(value: str) -> Harness | None:
    return value if value in ALL_HARNESSES else None


def _validate_sqlite(harness: Harness, path: Path) -> None:
    try:
        validate_sqlite_root(harness, path)
    except ValueError as error:
        raise ConfigurationError(str(error)) from error


def parse_roots(values: list[str] | None) -> dict[Harness, tuple[Path, ...]]:
    """Parse and validate repeatable HARNESS=PATH overrides."""
    grouped: dict[Harness, list[Path]] = {}
    for value in values or []:
        name, separator, raw_path = value.partition("=")
        harness = _harness(name)
        if not separator or harness is None or not raw_path.strip():
            message = f"invalid root mapping: {value!r}"
            raise ConfigurationError(message)
        path = Path(raw_path).expanduser().resolve()
        if harness in {"omp", "pi", "codex"}:
            if not path.is_dir():
                message = f"{harness} root is not a directory: {path}"
                raise ConfigurationError(message)
        elif not path.is_file():
            message = f"{harness} root is not a database file: {path}"
            raise ConfigurationError(message)
        grouped.setdefault(harness, []).append(path)

    roots: dict[Harness, tuple[Path, ...]] = {
        harness: tuple(dict.fromkeys(paths)) for harness, paths in grouped.items()
    }
    for harness in ("t3code", "opencode"):
        for path in roots.get(harness, ()):
            _validate_sqlite(harness, path)
    conflict = set(roots.get("omp", ())).intersection(roots.get("pi", ()))
    if conflict:
        message = f"OMP and Pi roots conflict: {min(conflict)}"
        raise ConfigurationError(message)
    return roots


def _parse_harnesses(values: list[str] | None) -> tuple[Harness, ...]:
    harnesses: list[Harness] = []
    for value in values or ALL_HARNESSES:
        harness = _harness(value)
        if harness is None:
            message = f"unknown harness: {value}"
            raise ConfigurationError(message)
        harnesses.append(harness)
    return tuple(dict.fromkeys(harnesses))


def build_config(
    harness_values: list[str] | None,
    root_values: list[str] | None,
) -> SearchConfig:
    """Validate filters and roots after argparse has parsed all flags."""
    roots = parse_roots(root_values)
    return SearchConfig(harnesses=_parse_harnesses(harness_values), roots=roots)


def search(config: SearchConfig, query: list[str], limit: int) -> list[Record]:
    """Discover every selected backend and return ranked records."""
    terms = tuple(term.casefold() for value in query for term in value.split() if term)
    if not terms:
        message = "query must not be empty"
        raise ConfigurationError(message)
    selected = set(config.harnesses)
    sessions = []
    sessions.extend(discover_jsonl_sessions(selected, config.roots))
    sessions.extend(discover_sqlite_sessions(selected, config.roots))
    return rank(sessions, terms, limit)
