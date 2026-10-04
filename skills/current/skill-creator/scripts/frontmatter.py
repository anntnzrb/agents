# Copyright (c) 2026
"""Read skill frontmatter with structured errors for validation and lint."""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeIs

import yaml

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class Frontmatter:
    """Parsed metadata, source lines, and caller-renderable failure details."""

    lines: tuple[str, ...] = ()
    metadata: dict[str, object] | None = None
    error: str | None = None
    yaml_error: bool = False


def _is_metadata(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def read_frontmatter(text: str) -> Frontmatter:
    """Extract delimiters once and parse YAML without choosing caller output."""
    if not text.startswith("---"):
        return Frontmatter(error="No YAML frontmatter found")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if match is None:
        return Frontmatter(error="Invalid frontmatter format")
    lines = tuple(match.group(1).splitlines())
    load: Callable[..., object] = yaml.safe_load
    try:
        raw = load(match.group(1))
    except yaml.YAMLError as exc:
        return Frontmatter(
            lines=lines, error=f"Invalid YAML in frontmatter: {exc}", yaml_error=True
        )
    if not _is_metadata(raw):
        return Frontmatter(lines=lines, error="Frontmatter must be a YAML dictionary")
    return Frontmatter(lines=lines, metadata=raw)
