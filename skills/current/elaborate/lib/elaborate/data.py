# Copyright (c) 2026
"""Typed persisted records and JSON boundary helpers."""

import hashlib
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict, TypeIs, cast

if TYPE_CHECKING:
    from collections.abc import Callable

type Value = str | int | float | bool | list[Value] | dict[str, Value] | None
UNIT_ID_WIDTH = 3

type Table = dict[str, Value]


class InputError(ValueError):
    """Invalid user configuration, input, or work directory."""


class Unit(TypedDict):
    """One manifest unit."""

    id: str
    chapter: int
    part: int
    parts: int
    title: str
    kind: str
    words: int
    images: int
    source: str
    sha256: str


class Book(TypedDict):
    """Source metadata."""

    title: str
    authors: list[str]
    language: str
    identifier: str


class Manifest(TypedDict):
    """Work directory manifest."""

    schema: int
    source: dict[str, str]
    book: Book
    config_sha256: str
    cover: str | None
    units: list[Unit]


class Facts(TypedDict):
    """Facts extracted from a source unit."""

    quotes: list[str]
    numbers: list[str]
    proper_nouns: list[str]
    hedges: dict[str, int]
    rare_words: list[str]
    headings: list[str]
    words: int
    images: NotRequired[list[str]]


class GateResult(TypedDict):
    """A measurable gate outcome."""

    id: str
    category: str
    status: str
    message: str
    details: list[str]


class Report(TypedDict):
    """Cached unit check."""

    unit: str
    key: str
    status: str
    gates: list[GateResult]
    metrics: Table


def _mapping(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def _key(value: object) -> str:
    if not isinstance(value, str):
        raise InputError("Object keys must be strings")
    return value


def _sequence(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def narrow(value: object) -> Value:
    """Validate unknown decoded data recursively."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if _mapping(value):
        return {_key(key): narrow(item) for key, item in value.items()}
    if _sequence(value):
        return [narrow(item) for item in value]
    raise InputError("Unsupported data value")


def table(value: Value) -> Table:
    """Require an object."""
    if not isinstance(value, dict):
        raise InputError("Expected a table/object")
    return value


def string(value: Value) -> str:
    """Require a string."""
    if not isinstance(value, str):
        raise InputError("Expected a string")
    return value


def integer(value: Value) -> int:
    """Require an integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError("Expected an integer")
    return value


def number(value: Value) -> float:
    """Require a finite numeric value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError("Expected a number")
    result = float(value)
    if not math.isfinite(result):
        raise InputError("Expected a finite number")
    return result


def strings(value: Value) -> list[str]:
    """Require a string list."""
    if not isinstance(value, list):
        raise InputError("Expected a string list")
    return [string(item) for item in value]


def canonical(value: object) -> str:
    """Encode deterministic readable JSON."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def digest(value: str | bytes) -> str:
    """Hash bytes or UTF-8 text."""
    return hashlib.sha256(
        value.encode() if isinstance(value, str) else value
    ).hexdigest()


def read_json(path: Path) -> Table:
    """Decode and narrow a JSON file."""
    decode = cast("Callable[[str], object]", json.loads)
    try:
        raw: object = decode(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise InputError(f"Invalid JSON file {path}: {error}") from error
    return table(narrow(raw))


def write_json(path: Path, value: object) -> None:
    """Write deterministic JSON, creating its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(canonical(value), encoding="utf-8")


def read_manifest(work: Path) -> Manifest:
    """Validate the persisted manifest at the filesystem boundary."""
    raw = read_json(work / "manifest.json")
    book = table(raw["book"])
    items = raw["units"]
    if integer(raw["schema"]) != 1 or not isinstance(items, list):
        raise InputError("Unsupported manifest schema")
    units: list[Unit] = []
    for item in items:
        unit = table(item)
        uid = string(unit["id"])
        if not uid.isdecimal() or len(uid) < UNIT_ID_WIDTH:
            raise InputError(f"Invalid unit id: {uid}")
        source = string(unit["source"])
        if source != f"source/{uid}.md":
            raise InputError(f"Invalid source path for {uid}")
        units.append(
            Unit(
                id=uid,
                chapter=integer(unit["chapter"]),
                part=integer(unit["part"]),
                parts=integer(unit["parts"]),
                title=string(unit["title"]),
                kind=string(unit["kind"]),
                words=integer(unit["words"]),
                images=integer(unit["images"]),
                source=source,
                sha256=string(unit["sha256"]),
            )
        )
    cover = raw["cover"]
    if cover is not None:
        cover = string(cover)
        if Path(cover).name != cover:
            raise InputError("Invalid cover path")
    return Manifest(
        schema=1,
        source={k: string(v) for k, v in table(raw["source"]).items()},
        book=Book(
            title=string(book["title"]),
            authors=strings(book["authors"]),
            language=string(book["language"]),
            identifier=string(book["identifier"]),
        ),
        config_sha256=string(raw["config_sha256"]),
        cover=cover,
        units=units,
    )


def read_facts(path: Path) -> Facts:
    """Validate a protected-facts file."""
    raw = read_json(path)
    return Facts(
        quotes=strings(raw["quotes"]),
        numbers=strings(raw["numbers"]),
        proper_nouns=strings(raw["proper_nouns"]),
        hedges={k: integer(v) for k, v in table(raw["hedges"]).items()},
        rare_words=strings(raw["rare_words"]),
        headings=strings(raw["headings"]),
        words=integer(raw["words"]),
        images=strings(raw.get("images", [])),
    )
