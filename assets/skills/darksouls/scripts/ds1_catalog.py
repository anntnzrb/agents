"""Deterministic Dark Souls Remastered catalog and mechanics helpers.

The data files are intentionally curated rather than a claim of a complete game
extract.  Attack-rating helpers are explicitly approximate: only weapons in the
curated catalog are accepted, and callers should confirm the final number in the
in-game status screen.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, cast, overload


_ROOT = Path(__file__).resolve().parent.parent
_RESOURCE_DIR = _ROOT / "resources"


class CatalogError(ValueError):
    """Readable, user-facing catalog or mechanics input error."""


class UnknownCatalogEntry(CatalogError):
    """Raised when a lookup cannot identify one catalogued entry."""


Record = dict[str, Any]


def _read_json(filename: str) -> dict[str, Any]:
    path = _RESOURCE_DIR / filename
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise CatalogError(f"DS1 catalog resource is missing: {filename}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"DS1 catalog resource is invalid JSON: {filename}") from exc
    if not isinstance(value, dict):
        raise CatalogError(f"DS1 catalog resource must contain an object: {filename}")
    return cast(dict[str, Any], value)


def _record_list(
    resource: Mapping[str, Any], key: str, filename: str
) -> tuple[Record, ...]:
    """Read one resource list and validate its JSON object entries."""
    raw = resource.get(key)
    if not isinstance(raw, list):
        raise CatalogError(
            f"DS1 catalog resource key '{key}' must contain a list: {filename}"
        )
    records: list[Record] = []
    for index, value in enumerate(raw):
        if not isinstance(value, dict):
            raise CatalogError(
                f"DS1 catalog resource list '{key}' entry {index} must contain an object: {filename}"
            )
        records.append(cast(Record, value))
    return tuple(records)


def _mapping(resource: Mapping[str, Any], key: str, filename: str) -> dict[str, Any]:
    """Read one required resource object and narrow its JSON shape."""
    raw = resource.get(key)
    if not isinstance(raw, dict):
        raise CatalogError(
            f"DS1 catalog resource key '{key}' must contain an object: {filename}"
        )
    return cast(dict[str, Any], raw)


@lru_cache(maxsize=None)
def _game_data() -> dict[str, Any]:
    return _read_json("game_data.json")


@lru_cache(maxsize=None)
def _weapons() -> tuple[Record, ...]:
    return _record_list(_read_json("weapons.json"), "weapons", "weapons.json")


@lru_cache(maxsize=None)
def _rings() -> tuple[Record, ...]:
    return _record_list(_read_json("rings.json"), "rings", "rings.json")


@lru_cache(maxsize=None)
def _goods_magic() -> dict[str, tuple[Record, ...]]:
    raw = _read_json("goods_magic.json")
    return {
        key: _record_list(raw, key, "goods_magic.json")
        for key, value in raw.items()
        if isinstance(value, list)
    }


GAME_DATA = _game_data()
WEAPONS = _weapons()
RINGS = _rings()
GOODS_MAGIC = _goods_magic()
ORIGINS = _record_list(GAME_DATA, "origins", "game_data.json")
UPGRADE_PATHS = _mapping(GAME_DATA, "upgrade_paths", "game_data.json")
BUILD_ARCHETYPES = _mapping(GAME_DATA, "build_archetypes", "game_data.json")
COVENANTS = _record_list(GAME_DATA, "covenants", "game_data.json")
FARMING_ROUTES = _record_list(GAME_DATA, "farming_routes", "game_data.json")
SPELL_TYPE_KEY = {
    "sorcery": "sorceries",
    "sorceries": "sorceries",
    "pyromancy": "pyromancies",
    "pyromancies": "pyromancies",
    "miracle": "miracles",
    "miracles": "miracles",
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _matches(
    records: Iterable[dict[str, Any]], query: str, *, label: str
) -> list[dict[str, Any]]:
    q = _norm(query)
    if not q:
        raise CatalogError(f"{label} lookup requires a non-empty name or filter")
    all_records = list(records)
    exact = [record for record in all_records if _norm(record.get("name", "")) == q]
    matches = exact or [
        record for record in all_records if q in _norm(record.get("name", ""))
    ]
    if not matches:
        sample = ", ".join(
            sorted(
                (str(item.get("name", "")) for item in all_records), key=str.casefold
            )[:8]
        )
        raise UnknownCatalogEntry(
            f"Unknown DS1 {label} '{query}'. Catalog examples: {sample}"
        )
    return sorted(matches, key=lambda item: str(item.get("name", "")).casefold())


@overload
def _copy(record: Mapping[str, Any]) -> dict[str, Any]: ...


@overload
def _copy(record: list[Any]) -> list[Any]: ...


def _copy(record: Mapping[str, Any] | list[Any]) -> dict[str, Any] | list[Any]:
    # JSON round-trip gives callers an independent result without exposing cache state.
    value = json.loads(json.dumps(record))
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    if isinstance(value, list):
        return cast(list[Any], value)
    raise CatalogError("DS1 catalog record could not be copied")


def _string_values(value: object, *, context: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise CatalogError(f"DS1 {context} must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise CatalogError(f"DS1 {context} must be a list of strings")
    return tuple(cast(str, item) for item in value)


def list_weapons(
    query: str = "", *, category: str = "", upgrade_path: str = ""
) -> list[dict[str, Any]]:
    """Return deterministic weapon records filtered by name/category/path."""
    records: Iterable[dict[str, Any]] = WEAPONS
    if query:
        records = _matches(records, query, label="weapon")
    if category:
        cat = _norm(category)
        records = [item for item in records if _norm(item.get("category", "")) == cat]
    if upgrade_path:
        path = _norm(upgrade_path)
        if path not in {_norm(item) for item in UPGRADE_PATHS}:
            raise CatalogError(
                f"Unknown DS1 upgrade path '{upgrade_path}'. Known paths: {', '.join(sorted(UPGRADE_PATHS))}"
            )
        records = [
            item
            for item in records
            if path in {_norm(item) for item in item.get("upgrade_paths", ())}
        ]
    return [
        _copy(item)
        for item in sorted(
            records, key=lambda item: str(item.get("name", "")).casefold()
        )
    ]


def weapon_lookup(name: str) -> dict[str, Any]:
    """Resolve exactly one curated weapon, rejecting ambiguous partial names."""
    matches = _matches(WEAPONS, name, label="weapon")
    if len(matches) != 1:
        names = ", ".join(item["name"] for item in matches)
        raise CatalogError(
            f"Weapon query '{name}' is ambiguous; choose one of: {names}"
        )
    return _copy(matches[0])


def list_rings(
    query: str = "", *, category: str = "", build: str = ""
) -> list[dict[str, Any]]:
    records: Iterable[dict[str, Any]] = RINGS
    if query:
        records = _matches(records, query, label="ring")
    if category:
        cat = _norm(category)
        records = [item for item in records if _norm(item.get("category", "")) == cat]
    if build:
        key = _norm(build)
        candidates = {key, str(build).casefold()}
        if not any(_norm(item) in candidates for item in BUILD_ARCHETYPES):
            raise CatalogError(
                f"Unknown DS1 build archetype '{build}'. Known builds: {', '.join(sorted(BUILD_ARCHETYPES))}"
            )
        records = [
            item
            for item in records
            if "all" in item.get("builds", ())
            or key in {_norm(v) for v in item.get("builds", ())}
        ]
    return [
        _copy(item)
        for item in sorted(
            records, key=lambda item: str(item.get("name", "")).casefold()
        )
    ]


def ring_lookup(name: str) -> dict[str, Any]:
    matches = _matches(RINGS, name, label="ring")
    if len(matches) != 1:
        raise CatalogError(
            f"Ring query '{name}' is ambiguous; choose one of: {', '.join(item['name'] for item in matches)}"
        )
    return _copy(matches[0])


def list_goods(
    query: str = "", *, kind: str = "", spell_type: str = ""
) -> list[dict[str, Any]]:
    """List spells and goods; ``kind`` accepts sorcery/pyromancy/miracle/goods."""
    records: list[dict[str, Any]] = []
    selected = SPELL_TYPE_KEY.get(spell_type.casefold(), "") if spell_type else ""
    if kind:
        key = kind.casefold()
        if key in SPELL_TYPE_KEY:
            selected = SPELL_TYPE_KEY[key]
        elif key in GOODS_MAGIC:
            selected = key
        else:
            raise CatalogError(
                f"Unknown DS1 goods/spell kind '{kind}'. Known kinds: sorcery, pyromancy, miracle, goods"
            )
    keys = [selected] if selected else list(GOODS_MAGIC)
    for key in keys:
        for item in GOODS_MAGIC.get(key, ()):
            record = _copy(item)
            record["kind"] = key
            records.append(record)
    if query:
        records = _matches(records, query, label="goods/spell")
    return sorted(
        records,
        key=lambda item: (str(item.get("name", "")).casefold(), item.get("kind", "")),
    )


def goods_lookup(name: str, *, kind: str = "") -> dict[str, Any]:
    selected = SPELL_TYPE_KEY.get(
        kind.casefold(), "goods" if kind.casefold() == "goods" else ""
    )
    if kind and not selected:
        raise CatalogError(
            f"Unknown DS1 goods/spell kind '{kind}'. Known kinds: sorcery, pyromancy, miracle, goods"
        )
    if selected:
        source = (item | {"kind": selected} for item in GOODS_MAGIC.get(selected, ()))
    else:
        source = (
            item | {"kind": key}
            for key, values in GOODS_MAGIC.items()
            for item in values
        )
    matches = _matches(source, name, label="goods/spell")
    if len(matches) != 1:
        raise CatalogError(
            f"Goods/spell query '{name}' is ambiguous; choose one of: {', '.join(item['name'] for item in matches)}"
        )
    return _copy(matches[0])


def origin_lookup(name: str) -> dict[str, Any]:
    matches = _matches(ORIGINS, name, label="origin")
    if len(matches) != 1:
        raise CatalogError(
            f"Origin query '{name}' is ambiguous; choose one of: {', '.join(item['name'] for item in matches)}"
        )
    return _copy(matches[0])


def list_origins() -> list[dict[str, Any]]:
    return [
        _copy(item)
        for item in sorted(ORIGINS, key=lambda item: item["name"].casefold())
    ]


def upgrade_path_lookup(name: str) -> dict[str, Any]:
    key = next((key for key in UPGRADE_PATHS if _norm(key) == _norm(name)), None)
    if key is None:
        raise CatalogError(
            f"Unknown DS1 upgrade path '{name}'. Known paths: {', '.join(sorted(UPGRADE_PATHS))}"
        )
    metadata = UPGRADE_PATHS[key]
    result: dict[str, Any]
    if isinstance(metadata, Mapping):
        result = cast(dict[str, Any], _copy(metadata))
    elif isinstance(metadata, list):
        # Keep list-shaped schedules under a named field rather than indexing
        # them as though they were path metadata mappings.
        result = {"path": _copy(metadata)}
    else:
        raise CatalogError(f"DS1 upgrade path '{key}' has invalid metadata")
    result["name"] = key
    return result


def soul_cost(target_level: int) -> int:
    """Return the documented approximate soul cost to reach ``target_level``."""
    if (
        isinstance(target_level, bool)
        or not isinstance(target_level, int)
        or target_level < 2
        or target_level > 713
    ):
        raise CatalogError("DS1 target level must be an integer from 2 through 713")
    formula = (
        0.02 * target_level**3 + 3.06 * target_level**2 + 105.6 * target_level - 895
    )
    return max(0, math.floor(formula))


_GRADE_FACTOR = {
    "-": 0.0,
    "E": 0.10,
    "D": 0.20,
    "C": 0.35,
    "B": 0.50,
    "A": 0.75,
    "S": 1.00,
}


def _stats(stats: Mapping[str, Any] | None) -> dict[str, float]:
    source = stats or {}
    result: dict[str, float] = {}
    for key in ("strength", "dexterity", "intelligence", "faith"):
        value = source.get(key, 40)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CatalogError(f"DS1 stat '{key}' must be numeric")
        result[key] = max(0.0, float(value))
    return result


def _upgrade_factor(path: str, level: int) -> float:
    limits = {
        "normal": 15,
        "raw": 5,
        "fire": 10,
        "chaos": 5,
        "lightning": 5,
        "magic": 10,
        "enchanted": 5,
        "crystal": 5,
        "divine": 10,
        "occult": 5,
        "unique": 5,
        "dragon": 5,
        "pyromancy": 15,
    }
    key = next((name for name in limits if _norm(name) == _norm(path)), None)
    if key is None:
        raise CatalogError(
            f"Unknown DS1 upgrade path '{path}'. Known paths: {', '.join(sorted(limits))}"
        )
    if (
        isinstance(level, bool)
        or not isinstance(level, int)
        or level < 0
        or level > limits[key]
    ):
        raise CatalogError(
            f"Upgrade level for {key} must be an integer from 0 through {limits[key]}"
        )
    if key == "normal":
        return 1.0 + 0.035 * level
    if key in {"fire", "divine", "pyromancy"}:
        return 1.0 + 0.045 * level
    if key in {"raw", "lightning", "chaos", "occult", "crystal", "enchanted", "magic"}:
        return 1.0 + 0.07 * level
    return 1.0 + 0.08 * level


def weapon_ar(
    weapon: str | Mapping[str, Any],
    stats: Mapping[str, Any] | None = None,
    *,
    upgrade_path: str = "normal",
    upgrade_level: int = 0,
    strict_requirements: bool = False,
) -> dict[str, Any]:
    """Estimate attack rating for one curated weapon and return its breakdown.

    This deliberately avoids pretending to reproduce FromSoftware's hidden AR
    tables.  It is deterministic and useful for comparing candidates only.
    """
    record = weapon_lookup(weapon) if isinstance(weapon, str) else dict(weapon)
    if not record.get("name") or not any(
        _norm(record.get("name", "")) == _norm(item.get("name", "")) for item in WEAPONS
    ):
        raise UnknownCatalogEntry(
            "AR estimation only supports weapons in the curated DS1 catalog"
        )
    if record.get("category") in {"catalyst", "talisman", "pyromancy_flame"}:
        raise CatalogError(
            f"AR estimation is not defined for DS1 spell tools such as '{record['name']}'"
        )
    path = next(
        (
            item
            for item in record.get("upgrade_paths", ())
            if _norm(item) == _norm(upgrade_path)
        ),
        None,
    )
    if path is None:
        raise CatalogError(
            f"Weapon '{record['name']}' does not support DS1 upgrade path '{upgrade_path}'"
        )
    factor = _upgrade_factor(path, upgrade_level)
    values = _stats(stats)
    requirements = record.get("requirements", {})
    shortfalls = {
        key: int(requirements.get(key, 0) - values[key])
        for key in ("strength", "dexterity", "intelligence", "faith")
        if values[key] < requirements.get(key, 0)
    }
    if strict_requirements and shortfalls:
        detail = ", ".join(f"{key} {value}" for key, value in shortfalls.items())
        raise CatalogError(f"Insufficient stats for {record['name']}: {detail}")
    scales = record.get("scaling", {})
    phys = float(record.get("base_attack", {}).get("physical", 0)) * (
        1
        + 0.6
        * _GRADE_FACTOR.get(scales.get("strength", "-"), 0)
        * values["strength"]
        / 40
        + 0.4
        * _GRADE_FACTOR.get(scales.get("dexterity", "-"), 0)
        * values["dexterity"]
        / 40
    )
    magic = float(record.get("base_attack", {}).get("magic", 0)) * (
        1
        + _GRADE_FACTOR.get(scales.get("intelligence", "-"), 0)
        * values["intelligence"]
        / 40
    )
    fire = float(record.get("base_attack", {}).get("fire", 0)) * (
        1
        + 0.5
        * _GRADE_FACTOR.get(scales.get("intelligence", "-"), 0)
        * values["intelligence"]
        / 40
        + 0.5 * _GRADE_FACTOR.get(scales.get("faith", "-"), 0) * values["faith"] / 40
    )
    lightning = float(record.get("base_attack", {}).get("lightning", 0)) * (
        1 + _GRADE_FACTOR.get(scales.get("faith", "-"), 0) * values["faith"] / 40
    )
    components = {
        "physical": round(phys * factor, 1),
        "magic": round(magic * factor, 1),
        "fire": round(fire * factor, 1),
        "lightning": round(lightning * factor, 1),
    }
    return {
        "name": record["name"],
        "upgrade_path": path,
        "upgrade_level": upgrade_level,
        "approximate": True,
        "components": components,
        "estimated_ar": round(sum(components.values()), 1),
        "requirements_met": not shortfalls,
        "shortfalls": shortfalls,
        "warning": "Approximate catalog estimate; confirm exact AR in the DS1/Remastered status screen.",
    }


def compare_weapons(
    names: Iterable[str],
    stats: Mapping[str, Any] | None = None,
    *,
    upgrade_path: str = "normal",
    upgrade_level: int = 0,
) -> list[dict[str, Any]]:
    values = list(names)
    if not values:
        raise CatalogError("Weapon comparison requires at least one weapon name")
    results = [
        weapon_ar(name, stats, upgrade_path=upgrade_path, upgrade_level=upgrade_level)
        for name in values
    ]
    return sorted(
        results, key=lambda item: (-item["estimated_ar"], item["name"].casefold())
    )


def equip_load_state(current_weight: object, max_load: object) -> dict[str, Any]:
    if (
        not isinstance(current_weight, (int, float))
        or not isinstance(max_load, (int, float))
        or max_load <= 0
        or current_weight < 0
    ):
        raise CatalogError(
            "Current weight must be non-negative and max equip load must be positive"
        )
    fraction = float(current_weight) / float(max_load)
    if fraction <= 0.25:
        roll = "fast"
    elif fraction <= 0.50:
        roll = "medium"
    elif fraction <= 1.0:
        roll = "fat"
    else:
        roll = "overburdened"
    return {
        "current_weight": current_weight,
        "max_load": max_load,
        "fraction": round(fraction, 4),
        "percent": round(fraction * 100, 2),
        "roll": roll,
    }


def estus_totals(
    *, kindled: object = 0, rite_of_kindling: bool = False, fire_keeper: bool = False
) -> dict[str, Any]:
    if (
        isinstance(kindled, bool)
        or not isinstance(kindled, int)
        or kindled < 0
        or kindled > (3 if rite_of_kindling else 1)
    ):
        limit = 3 if rite_of_kindling else 1
        raise CatalogError(
            f"Kindled bonfire count must be an integer from 0 through {limit}"
        )
    if fire_keeper:
        total = 10
    else:
        total = min(20 if rite_of_kindling else 10, 5 + (5 * kindled))
    return {
        "flasks": total,
        "kindled": kindled,
        "rite_of_kindling": rite_of_kindling,
        "fire_keeper": fire_keeper,
    }


def build_recommendations(build: str) -> dict[str, Any]:
    key = next((name for name in BUILD_ARCHETYPES if _norm(name) == _norm(build)), None)
    if key is None:
        raise CatalogError(
            f"Unknown DS1 build archetype '{build}'. Known builds: {', '.join(sorted(BUILD_ARCHETYPES))}"
        )
    raw_archetype = BUILD_ARCHETYPES[key]
    if not isinstance(raw_archetype, Mapping):
        raise CatalogError(f"DS1 build archetype '{key}' has invalid metadata")
    archetype = cast(dict[str, Any], _copy(raw_archetype))
    weapons: list[dict[str, Any]] = []
    for name in _string_values(
        archetype.get("safe_defaults", ()),
        context=f"build archetype '{key}' safe_defaults",
    ):
        try:
            weapons.append(weapon_lookup(name))
        except CatalogError:
            pass
    return {
        "name": key,
        "archetype": archetype,
        "weapons": weapons,
        "rings": list_rings(build=key),
    }


def catalog_lookup(kind: str, query: str) -> dict[str, Any]:
    """Resolve one entry through a stable kind/name interface for CLI callers."""
    key = _norm(kind)
    if key in {"weapon", "weapons"}:
        return weapon_lookup(query)
    if key in {"ring", "rings"}:
        return ring_lookup(query)
    if key in {
        "good",
        "goods",
        "spell",
        "spells",
        "sorcery",
        "sorceries",
        "pyromancy",
        "pyromancies",
        "miracle",
        "miracles",
    }:
        return goods_lookup(
            query, kind=key if key not in {"good", "spell", "spells"} else ""
        )
    if key in {"origin", "origins", "class", "classes"}:
        return origin_lookup(query)
    raise CatalogError(
        "Unknown DS1 catalog kind '{}'; choose weapon, ring, goods, spell, or origin".format(
            kind
        )
    )


def audit_catalog() -> list[str]:
    """Validate the catalog resource files and their expected top-level shapes."""
    schemas: dict[str, dict[str, type[object]]] = {
        "game_data.json": {
            "game": str,
            "origins": list,
            "upgrade_paths": dict,
            "build_archetypes": dict,
            "covenants": list,
            "farming_routes": list,
        },
        "weapons.json": {"game": str, "weapons": list},
        "rings.json": {"game": str, "rings": list},
        "goods_magic.json": {
            "game": str,
            "sorceries": list,
            "pyromancies": list,
            "miracles": list,
            "goods": list,
        },
    }
    entry_schemas: dict[str, dict[str, type[object]]] = {
        # Farming routes are identified by ``id`` and presented by ``label``;
        # unlike catalog entries, they intentionally do not have a ``name``.
        "farming_routes": {
            "id": str,
            "label": str,
            "resource": str,
            "spoiler_level": int,
            "notes": str,
        },
    }
    errors: list[str] = []
    for filename, expected in schemas.items():
        try:
            resource = _read_json(filename)
        except CatalogError as exc:
            errors.append(str(exc))
            continue
        for key, expected_type in expected.items():
            if key not in resource:
                errors.append(f"{filename} missing top-level key '{key}'")
                continue
            if not isinstance(resource[key], expected_type):
                errors.append(
                    f"{filename} top-level key '{key}' must be a {expected_type.__name__}"
                )
        for key, expected_type in expected.items():
            raw_records = resource.get(key)
            if expected_type is not list or not isinstance(raw_records, list):
                continue
            for index, candidate in enumerate(cast(list[object], raw_records)):
                if not isinstance(candidate, Mapping):
                    errors.append(
                        f"{filename} top-level list '{key}' entry {index} is not an object"
                    )
                    continue
                record = cast(Mapping[str, object], candidate)
                required = entry_schemas.get(key)
                if required is None:
                    if key != "origins" and not isinstance(record.get("name"), str):
                        errors.append(
                            f"{filename} top-level list '{key}' entry {index} is missing a name"
                        )
                    continue
                for field, field_type in required.items():
                    if field not in record:
                        errors.append(
                            f"{filename} top-level list '{key}' entry {index} is missing required field '{field}'"
                        )
                        continue
                    value = record[field]
                    valid_type = isinstance(value, field_type) and not (
                        field_type is int and isinstance(value, bool)
                    )
                    if not valid_type:
                        errors.append(
                            f"{filename} top-level list '{key}' entry {index} field '{field}' "
                            f"must be a {field_type.__name__}"
                        )
    upgrade_paths_raw = GAME_DATA.get("upgrade_paths")
    if isinstance(upgrade_paths_raw, Mapping):
        upgrade_paths = cast(Mapping[object, object], upgrade_paths_raw)
        for key, metadata in upgrade_paths.items():
            if not isinstance(key, str) or not isinstance(metadata, Mapping):
                errors.append(
                    "game_data.json upgrade_paths entries must map names to objects"
                )
                break
    return errors


__all__ = [
    "CatalogError",
    "UnknownCatalogEntry",
    "GAME_DATA",
    "WEAPONS",
    "RINGS",
    "GOODS_MAGIC",
    "ORIGINS",
    "UPGRADE_PATHS",
    "BUILD_ARCHETYPES",
    "COVENANTS",
    "FARMING_ROUTES",
    "SPELL_TYPE_KEY",
    "list_weapons",
    "weapon_lookup",
    "list_rings",
    "ring_lookup",
    "list_goods",
    "goods_lookup",
    "catalog_lookup",
    "origin_lookup",
    "list_origins",
    "upgrade_path_lookup",
    "audit_catalog",
    "soul_cost",
    "weapon_ar",
    "compare_weapons",
    "equip_load_state",
    "estus_totals",
    "build_recommendations",
]
