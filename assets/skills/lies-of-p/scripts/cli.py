# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Deterministic, dependency-free Lies of P companion CLI."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"
JsonValue = Any


def load(name: str) -> JsonValue:
    """Load a named resource, converting filesystem errors to CLI errors."""
    path = RESOURCES / name
    try:
        with path.open(encoding="utf-8") as resource:
            return json.load(resource)
    except (OSError, json.JSONDecodeError) as error:
        message = f"resource {name}: {error}"
        raise RuntimeError(message) from error


def emit(value: JsonValue, *, as_json: bool = False) -> None:
    """Write a command result to stdout using the public JSON formatting contract."""
    if as_json:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    elif isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    sys.stdout.write(f"{rendered}\n")


def rows(data: JsonValue, query: str = "") -> list[JsonValue]:
    """Return list or mapping values matching a case-insensitive query."""
    values = (
        data
        if isinstance(data, list)
        else list(data.values())
        if isinstance(data, dict)
        else []
    )
    folded = query.casefold()
    return [
        value
        for value in values
        if not folded
        or folded in json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()
    ]


def named_rows(data: JsonValue, query: str) -> list[JsonValue]:
    """Prefer an exact item-name match before broad full-record search."""
    values = rows(data)
    exact = [
        value
        for value in values
        if str(value.get("name", "")).casefold() == query.casefold()
    ]
    return exact or rows(data, query)


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    command_parser = argparse.ArgumentParser(prog="lies-of-p")
    command_parser.add_argument("--json", action="store_true", dest="as_json")
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    for name in (
        "fresh",
        "build",
        "weaknesses",
        "bosses",
        "route",
        "trophies",
        "checklist",
        "farm",
        "sources",
        "audit",
    ):
        subcommand = subcommands.add_parser(name)
        subcommand.add_argument("query", nargs="?", default="")
        subcommand.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            default=argparse.SUPPRESS,
        )
        if name == "build":
            subcommand.add_argument("--level", type=int)
        if name in ("bosses", "trophies", "route", "checklist"):
            subcommand.add_argument("--spoilers", action="store_true")
        if name in ("route", "checklist"):
            subcommand.add_argument("--chapter", type=int, required=True)
            subcommand.add_argument("--dlc", action="store_true")
        if name == "trophies":
            subcommand.add_argument("--dlc", action="store_true")
        if name == "sources":
            subcommand.add_argument(
                "mode",
                choices=("list", "status", "explain"),
                nargs="?",
                default="list",
            )
        if name == "farm":
            subcommand.add_argument("stage", nargs="?", default="")
    return command_parser


def without_spoilers(value: JsonValue, keys: tuple[str, ...]) -> list[JsonValue]:
    """Remove spoiler fields from matching mapping rows."""
    return [
        {key: item for key, item in row.items() if key not in keys} for row in value
    ]


def safe_bosses(data: JsonValue, query: str) -> JsonValue:
    """Expose only spoiler-safe base-game boss guidance."""
    all_rows = rows(data)
    base_rows = [row for row in all_rows if not row.get("dlc")]
    if not query:
        return {
            "count": len(base_rows),
            "guidance": (
                "Base-game bosses: learn attack timing, guard, and stagger; "
                "no-summon guidance."
            ),
            "types": ["puppet", "human", "monster"],
        }
    matches = [
        row
        for row in base_rows
        if query.casefold() in str(row.get("name", "")).casefold()
    ]
    if not matches and any(
        query.casefold() in str(row.get("name", "")).casefold()
        for row in all_rows
        if row.get("dlc")
    ):
        return {
            "count": 0,
            "guidance": (
                "That boss is future DLC content; rerun with --spoilers for "
                "its name and guidance."
            ),
        }
    return [
        {
            "name": row.get("name"),
            "guidance": "Base-game boss; use guard, stagger, and fatal attacks.",
        }
        for row in matches
    ]


def _fresh(_args: argparse.Namespace) -> JsonValue:
    game = load("game_data.json")
    return {key: game.get(key) for key in ("version", "difficulty", "build")}


def _build(args: argparse.Namespace) -> JsonValue:
    build = load("game_data.json").get("build", {})
    return {**build, **({"level": args.level} if args.level is not None else {})}


def _weaknesses(args: argparse.Namespace) -> JsonValue:
    return rows(load("game_data.json").get("enemy_classes", []), args.query)


def _bosses(args: argparse.Namespace) -> JsonValue:
    bosses = load("game_data.json").get("bosses", [])
    result = rows(bosses, args.query)
    return result if args.spoilers else safe_bosses(bosses, args.query)


def _route_or_checklist(args: argparse.Namespace) -> JsonValue:
    platinum = load("platinum.json")
    source = (
        platinum.get("chapters", [])
        if not args.dlc
        else platinum.get("overture_sections", [])
    )
    result = [
        item
        for item in rows(source, args.query)
        if item.get("chapter", item.get("number")) == args.chapter
    ]
    return (
        result
        if args.spoilers
        else without_spoilers(result, ("spoiler", "spoilers", "ending"))
    )


def _trophies(args: argparse.Namespace) -> JsonValue:
    platinum = load("platinum.json")
    result = named_rows(
        platinum.get("dlc") if args.dlc else platinum.get("base", []),
        args.query,
    )
    return (
        result if args.spoilers else without_spoilers(result, ("spoiler", "spoilers"))
    )


def _farm(args: argparse.Namespace) -> JsonValue:
    return rows(load("game_data.json").get("farms", []), args.stage)


def _sources(args: argparse.Namespace) -> JsonValue:
    registry = load("source_registry.json")
    if args.mode == "explain":
        return registry
    if args.mode == "list":
        return sorted(registry, key=str)
    return {key: value.get("checked") for key, value in registry.items()}


def _audit(_args: argparse.Namespace) -> JsonValue:
    expected = {
        "game_data.json": {
            "version",
            "difficulty",
            "build",
            "enemy_classes",
            "bosses",
            "farms",
            "areas",
        },
        "platinum.json": {
            "version",
            "base",
            "dlc",
            "chapters",
            "overture_sections",
            "endings",
            "collectibles",
        },
    }
    registry = load("source_registry.json")
    missing = {
        name: sorted(fields - set(load(name))) for name, fields in expected.items()
    }
    source_fields = (
        "url",
        "title",
        "kind",
        "checked",
        "version_scope",
        "confidence",
        "license_or_terms",
        "notes",
    )
    source_missing = {
        key: sorted(set(source_fields) - set(value))
        for key, value in registry.items()
        if not isinstance(value, dict) or set(source_fields) - set(value)
    }
    platinum = load("platinum.json")
    trophy_counts = {
        "base": len(platinum.get("base", [])),
        "dlc": len(platinum.get("dlc", [])),
    }
    missing["source_registry"] = source_missing
    return {
        "ok": not any(missing.values()) and trophy_counts == {"base": 43, "dlc": 11},
        "counts": {name: len(rows(load(name))) for name in expected},
        "trophy_counts": trophy_counts,
        "missing": missing,
        "sources": len(registry),
    }


CommandHandler = Callable[[argparse.Namespace], JsonValue]
COMMAND_HANDLERS: dict[str, CommandHandler] = {
    "fresh": _fresh,
    "build": _build,
    "weaknesses": _weaknesses,
    "bosses": _bosses,
    "route": _route_or_checklist,
    "checklist": _route_or_checklist,
    "trophies": _trophies,
    "farm": _farm,
    "sources": _sources,
    "audit": _audit,
}


def execute(args: argparse.Namespace) -> JsonValue:
    """Execute a parsed command and return its result."""
    return COMMAND_HANDLERS[args.command](args)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its process status."""
    args = parser().parse_args(argv)
    try:
        emit(execute(args), as_json=args.as_json)
    except (RuntimeError, AttributeError, TypeError, ValueError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
