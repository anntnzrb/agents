# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Deterministic, dependency-free Lies of P companion CLI."""

import argparse
import json
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TypedDict

type JSONScalar = None | bool | int | float | str
type JSONObject = Mapping[str, JSONValue]
type JSONArray = Sequence[JSONValue]
type JSONValue = JSONScalar | JSONArray | JSONObject
type CommandHandler = Callable[[argparse.Namespace], JSONValue]

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"
EXPECTED_JSON_OBJECT = "expected a JSON object"
EXPECTED_JSON_ARRAY = "expected a JSON array"
INVALID_JSON_RESOURCE = "resource is not valid JSON"
CANDIDATE_FIELD_COUNT = 5
PERCENT_MAX = 100.0
CANDIDATE_ERROR = "candidate must be NAME,PHYSICAL,ELEMENTAL,CRIT_PERCENT,WEIGHT"
CRIT_ERROR = "crit_percent must be between 0 and 100"
PHYSICAL_RETAINED_ERROR = "physical_retained must be between 0 and 1"
CRITICAL_MULTIPLIER_ERROR = "critical_multiplier must be at least 1"
ELEMENTAL_RETAINED_ERROR = "elemental_retained must be between 0 and 1"
COMPARE_METHOD = (
    "displayed_ar=physical+elemental; retained hit applies motion; "
    "optional critical multiplier"
)


class Candidate(TypedDict):
    """One user-entered inventory candidate."""

    name: str
    physical: float
    elemental: float
    crit_percent: float
    weight: float


class ComparisonRow(Candidate):
    """One calculated and ranked comparison row."""

    displayed_ar: float
    adjusted_hit: float
    expected_hit: float | None
    rank_value: float
    rank: int


def _number(value: str, label: str) -> float:
    """Parse a finite nonnegative numeric option."""
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        message = f"{label} must be nonnegative"
        raise ValueError(message)
    return parsed


def _candidate(value: str) -> Candidate:
    """Parse NAME,PHYSICAL,ELEMENTAL,CRIT_PERCENT,WEIGHT."""
    parts = value.split(",")
    if len(parts) != CANDIDATE_FIELD_COUNT or not parts[0].strip():
        raise ValueError(CANDIDATE_ERROR)
    physical = _number(parts[1], "physical")
    elemental = _number(parts[2], "elemental")
    crit = float(parts[3])
    weight = _number(parts[4], "weight")
    if not math.isfinite(crit) or not 0 <= crit <= PERCENT_MAX:
        raise ValueError(CRIT_ERROR)
    return {
        "name": parts[0].strip(),
        "physical": physical,
        "elemental": elemental,
        "crit_percent": crit,
        "weight": weight,
    }


def _comparison_json(row: ComparisonRow) -> JSONObject:
    """Project a typed calculation row into the JSON contract."""
    return {
        "name": row["name"],
        "physical": row["physical"],
        "elemental": row["elemental"],
        "crit_percent": row["crit_percent"],
        "weight": row["weight"],
        "displayed_ar": row["displayed_ar"],
        "adjusted_hit": row["adjusted_hit"],
        "expected_hit": row["expected_hit"],
        "rank_value": row["rank_value"],
        "rank": row["rank"],
    }


def _compare(args: argparse.Namespace) -> JSONValue:
    """Rank candidates using only the explicitly displayed, retained inputs."""
    candidates = [_candidate(item) for item in args.candidate]
    motion = _number(args.motion, "motion")
    physical_retained = float(args.physical_retained)
    elemental_retained = float(args.elemental_retained)
    if not 0 <= physical_retained <= 1 or not math.isfinite(physical_retained):
        raise ValueError(PHYSICAL_RETAINED_ERROR)
    if not 0 <= elemental_retained <= 1 or not math.isfinite(elemental_retained):
        raise ValueError(ELEMENTAL_RETAINED_ERROR)
    if args.critical_multiplier is None:
        multiplier = None
    else:
        multiplier = _number(args.critical_multiplier, "critical_multiplier")
        if multiplier < 1:
            raise ValueError(CRITICAL_MULTIPLIER_ERROR)
    result: list[ComparisonRow] = []
    for candidate in candidates:
        displayed = candidate["physical"] + candidate["elemental"]
        adjusted = (
            candidate["physical"] * physical_retained
            + candidate["elemental"] * elemental_retained
        ) * motion
        expected = (
            adjusted * (1 + candidate["crit_percent"] / 100 * (multiplier - 1))
            if multiplier is not None
            else None
        )
        result.append(
            {
                **candidate,
                "displayed_ar": displayed,
                "adjusted_hit": adjusted,
                "expected_hit": expected,
                "rank_value": expected if expected is not None else adjusted,
                "rank": 0,
            }
        )
    result.sort(key=lambda item: (-item["rank_value"], item["name"].casefold()))
    for rank, item in enumerate(result, 1):
        item["rank"] = rank
    return {
        "candidates": [_comparison_json(item) for item in result],
        "method": COMPARE_METHOD,
        "excluded": [
            "enemy defense",
            "hidden scaling/saturation",
            "animation DPS",
            "status buildup",
            "Fable effects",
        ],
    }


def _community(args: argparse.Namespace) -> JSONValue:
    """Query verified community sentiment while filtering spoiler-gated records."""
    resource = _dict(load("community.json"))
    if args.spoilers:
        return (
            resource
            if not args.query
            else {
                **resource,
                **{
                    key: rows(value, args.query) if isinstance(value, list) else value
                    for key, value in resource.items()
                },
            }
        )
    filtered: dict[str, JSONValue] = {}
    for key, value in resource.items():
        if not isinstance(value, list):
            filtered[key] = value
            continue
        filtered[key] = [
            row
            for row in rows(value, args.query)
            if not _dict(row).get("spoiler") and not _dict(row).get("dlc")
        ]
    return filtered


def _dict(value: JSONValue) -> JSONObject:
    """Narrow a JSON value to an object."""
    if not isinstance(value, dict):
        raise TypeError(EXPECTED_JSON_OBJECT)
    return value


def _list(value: JSONValue) -> JSONArray:
    """Narrow a JSON value to an array."""
    if not isinstance(value, list):
        raise TypeError(EXPECTED_JSON_ARRAY)
    return value


def load(name: str) -> JSONValue:
    """Load and validate one UTF-8 JSON resource."""
    path = RESOURCES / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        message = f"resource {name}: {error}"
        raise RuntimeError(message) from error
    if not isinstance(value, (type(None), bool, int, float, str, list, dict)):
        raise TypeError(INVALID_JSON_RESOURCE)
    return value


def rows(data: JSONValue, query: str = "") -> JSONArray:
    """Return resource values matching a case-insensitive query."""
    values: JSONArray
    if isinstance(data, list):
        values = data
    elif isinstance(data, dict):
        values = list(data.values())
    else:
        values = []
    folded = query.casefold()
    return [
        value
        for value in values
        if not folded
        or folded in json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()
    ]


def _records(value: JSONValue) -> list[JSONObject]:
    values: Sequence[JSONValue]
    if isinstance(value, list):
        values = value
    elif isinstance(value, dict):
        values = list(value.values())
    else:
        values = []
    return [_dict(row) for row in values]


def named_rows(data: JSONValue, query: str) -> list[JSONObject]:
    """Prefer an exact item-name match before broad record search."""
    values = _records(data)
    exact = [
        value
        for value in values
        if str(value.get("name", "")).casefold() == query.casefold()
    ]
    return exact or [_dict(value) for value in rows(data, query)]


def emit(value: JSONValue, *, as_json: bool = False) -> None:
    """Render a command result to stdout."""
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


def parser() -> argparse.ArgumentParser:
    """Build the public CLI argument parser."""
    command_parser = argparse.ArgumentParser(prog="lies-of-p")
    command_parser.add_argument("--json", action="store_true", dest="as_json")
    names = (
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
        "compare",
        "community",
    )
    subcommands = command_parser.add_subparsers(dest="command", required=True)
    for name in names:
        sub = subcommands.add_parser(name)
        if name not in ("sources", "audit", "compare"):
            sub.add_argument("query", nargs="?", default="")
        if name == "compare":
            sub.add_argument("--candidate", action="append", required=True)
            sub.add_argument("--motion", default="1.0")
            sub.add_argument("--critical-multiplier")
            sub.add_argument("--physical-retained", default="1.0")
            sub.add_argument("--elemental-retained", default="1.0")
        if name == "community":
            sub.add_argument("--spoilers", action="store_true")
        sub.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            default=argparse.SUPPRESS,
        )
        if name == "build":
            sub.add_argument("--level", type=int)
        if name in ("bosses", "trophies", "route", "checklist"):
            sub.add_argument("--spoilers", action="store_true")
        if name in ("route", "checklist"):
            sub.add_argument("--chapter", type=int, required=True)
            sub.add_argument("--dlc", action="store_true")
        if name == "trophies":
            sub.add_argument("--dlc", action="store_true")
        if name == "sources":
            sub.add_argument(
                "mode",
                choices=("list", "status", "explain"),
                nargs="?",
                default="list",
            )
    return command_parser


def without_spoilers(value: Sequence[JSONValue], keys: tuple[str, ...]) -> JSONArray:
    """Remove selected spoiler fields from result objects."""
    return [
        {key: item for key, item in _dict(row).items() if key not in keys}
        for row in value
    ]


def safe_bosses(data: JSONValue, query: str) -> JSONValue:
    """Expose spoiler-safe boss information until explicitly opted in."""
    all_rows = _records(data)
    base = [row for row in all_rows if not row.get("dlc")]
    if not query:
        return {
            "count": len(base),
            "guidance": (
                "Base-game bosses: learn attack timing, guard, and stagger; "
                "no-summon guidance."
            ),
            "types": ["puppet", "human", "monster"],
        }
    matches = [
        row for row in base if query.casefold() in str(row.get("name", "")).casefold()
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


def _fresh(_: argparse.Namespace) -> JSONValue:
    game = _dict(load("game_data.json"))
    return {key: game.get(key) for key in ("version", "difficulty", "build")}


def _build(args: argparse.Namespace) -> JSONValue:
    build = _dict(_dict(load("game_data.json")).get("build", {}))
    return {**build, **({"level": args.level} if args.level is not None else {})}


def _weaknesses(args: argparse.Namespace) -> JSONValue:
    return rows(_dict(load("game_data.json")).get("enemy_classes", []), args.query)


def _bosses(args: argparse.Namespace) -> JSONValue:
    bosses = _dict(load("game_data.json")).get("bosses", [])
    return (
        rows(bosses, args.query) if args.spoilers else safe_bosses(bosses, args.query)
    )


def _route_or_checklist(args: argparse.Namespace) -> JSONValue:
    platinum = _dict(load("platinum.json"))
    source = (
        platinum.get("chapters", [])
        if not args.dlc
        else platinum.get("overture_sections", [])
    )
    result = [
        item
        for item in rows(source, args.query)
        if _dict(item).get("chapter", _dict(item).get("number")) == args.chapter
    ]
    return (
        result
        if args.spoilers
        else without_spoilers(result, ("spoiler", "spoilers", "ending"))
    )


def _trophies(args: argparse.Namespace) -> JSONValue:
    platinum = _dict(load("platinum.json"))
    result = named_rows(
        platinum.get("dlc", []) if args.dlc else platinum.get("base", []),
        args.query,
    )
    return (
        result if args.spoilers else without_spoilers(result, ("spoiler", "spoilers"))
    )


def _farm(args: argparse.Namespace) -> JSONValue:
    return rows(_dict(load("game_data.json")).get("farms", []), args.query)


def _sources(args: argparse.Namespace) -> JSONValue:
    registry = _dict(load("source_registry.json"))
    if args.mode == "explain":
        return registry
    if args.mode == "status":
        return {key: _dict(value).get("checked") for key, value in registry.items()}
    return sorted(registry)


def _audit(_: argparse.Namespace) -> JSONValue:
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
        "community.json": {
            "version",
            "method",
            "weapons",
            "amulets",
            "boss_walls",
            "calculator_research",
        },
    }
    registry = _dict(load("source_registry.json"))
    missing: dict[str, JSONValue] = {
        name: sorted(fields - set(_dict(load(name))))
        for name, fields in expected.items()
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
    source_missing: dict[str, JSONValue] = {}
    for key, value in registry.items():
        if not isinstance(value, dict):
            source_missing[key] = list(source_fields)
            continue
        absent = sorted(set(source_fields) - set(value))
        if absent:
            source_missing[key] = absent
    community = _dict(load("community.json"))
    community_sources: set[str] = set()
    for group in ("weapons", "amulets", "boss_walls"):
        for record in _records(community.get(group, [])):
            community_sources.update(
                str(key) for key in _list(record.get("sources", []))
            )
    calculator = _dict(community.get("calculator_research", {}))
    community_sources.update(str(key) for key in _list(calculator.get("sources", [])))
    missing["community_sources"] = sorted(community_sources - set(registry))

    platinum = _dict(load("platinum.json"))
    trophy_counts = {
        "base": len(_list(platinum.get("base", []))),
        "dlc": len(_list(platinum.get("dlc", []))),
    }
    missing["source_registry"] = source_missing
    return {
        "ok": not any(missing.values()) and trophy_counts == {"base": 43, "dlc": 11},
        "counts": {name: len(_dict(load(name))) for name in expected},
        "trophy_counts": trophy_counts,
        "missing": missing,
        "sources": len(registry),
    }


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
    "compare": _compare,
    "community": _community,
}


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its process status."""
    try:
        args = parser().parse_args(argv)
        emit(COMMAND_HANDLERS[args.command](args), as_json=args.as_json)
    except (RuntimeError, TypeError, KeyError, ValueError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
