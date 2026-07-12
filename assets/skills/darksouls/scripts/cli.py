#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pycryptodome"]
# ///
"""Canonical spoiler-safe Dark Souls Remastered companion CLI."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Callable, Mapping, NoReturn, Sequence, TypedDict, cast

from ds1_core import (
    AREAS,
    ESTUS_MAX,
    ESTUS_SHARDS_MAX,
    FIRE_KEEPER_SOULS_MAX,
    KINDLING_LEVELS,
    ORIGINS,
    SOFTCAPS,
    SOURCES,
    UPGRADE_PATHS,
    audit_core,
    cache_dir,
    cache_get,
    equip_load_max,
    fetch_cached,
    load_guide_chunks,
    load_guide_manifest,
    load_json_resource,
    load_sources,
    transcript_summary,
    search_transcript,
    get_transcript_chunk,
    search_guide,
    soul_cost,
)

catalog: object | None = None
try:  # Sibling modules are supplied by the catalog/save workers before release.
    import ds1_catalog as _catalog
except ImportError:  # construction-time import only; commands fail clearly if absent
    pass
else:
    catalog = cast(object, _catalog)

save: object | None = None
try:
    import ds1_save as _save
except ImportError:
    pass
else:
    save = cast(object, _save)

frames: object | None = None


def _need_frames() -> object:
    global frames
    if frames is None:
        try:
            frames = cast(object, importlib.import_module("ds1_frames"))
        except ImportError:
            _die(
                "ds1_frames is not installed; complete the frame scanner module before running frames"
            )
    return frames


def _die(message: str, code: int = 2) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def _need_catalog() -> object:
    if catalog is None:
        _die(
            "ds1_catalog is not installed; complete the catalog module before running this command"
        )
    return catalog


def _need_save() -> object:
    if save is None:
        _die(
            "ds1_save is not installed; complete the save module before running save commands"
        )
    return save


def _value(args: argparse.Namespace, name: str) -> object:
    values = cast(Mapping[str, object], vars(args))
    return values.get(name)


def _required_str(args: argparse.Namespace, name: str) -> str:
    value = _value(args, name)
    if not isinstance(value, str):
        _die(f"argument {name!r} must be a string")
    return value


def _optional_str(args: argparse.Namespace, name: str) -> str | None:
    value = _value(args, name)
    if value is None:
        return None
    if not isinstance(value, str):
        _die(f"argument {name!r} must be a string or null")
    return value


def _required_int(args: argparse.Namespace, name: str) -> int:
    value = _value(args, name)
    if not isinstance(value, int) or isinstance(value, bool):
        _die(f"argument {name!r} must be an integer")
    return value


def _numeric_int(value: object, default: int = 0) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _flag(args: argparse.Namespace, name: str) -> bool:
    value = _value(args, name)
    if value is None:
        return False
    if not isinstance(value, bool):
        _die(f"argument {name!r} must be a boolean")
    return value


def _str_list(args: argparse.Namespace, name: str) -> list[str]:
    value = _value(args, name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _die(f"argument {name!r} must be a list of strings")
    return cast(list[str], value)


class _GuideRow(TypedDict):
    row: int
    h: list[str]
    k: str
    t: str


class _GuideResult(_GuideRow):
    snippet: str


def _guide_rows() -> list[_GuideRow]:
    return cast(list[_GuideRow], load_guide_chunks())


def _guide_manifest() -> Mapping[str, object]:
    return cast(Mapping[str, object], load_guide_manifest())


def _search_guide(
    query: str, *, kind: str | None = None, heading: str | None = None, limit: int = 8
) -> list[_GuideResult]:
    return cast(
        list[_GuideResult], search_guide(query, kind=kind, heading=heading, limit=limit)
    )


def _string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(str(item) for item in cast(Sequence[object], value))
    return ()


def _area_rows() -> tuple[Mapping[str, object], ...]:
    return cast(tuple[Mapping[str, object], ...], AREAS)


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return None


def _get_callable(module: object, name: str) -> Callable[..., object] | None:
    fn = cast(object, getattr(module, name, None))
    if callable(fn):
        return cast(Callable[..., object], fn)
    return None


def _call(
    module: object, names: Sequence[str], *args: object, **kwargs: object
) -> object:
    for name in names:
        fn = _get_callable(module, name)
        if fn is not None:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                _die(str(exc))
    _die(f"required API is missing: {' / '.join(names)}")


def _json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def _resource_rows(name: str, key: str | None = None) -> list[dict[str, object]]:
    value = cast(object, load_json_resource(name, []))
    if isinstance(value, Mapping) and key:
        selected = value.get(key)
        if isinstance(selected, list):
            value = selected
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    for row in cast(list[object], value):
        mapping = _as_mapping(row)
        if mapping is not None:
            rows.append(dict(mapping))
    return rows


def _name(value: object) -> str:
    if isinstance(value, str):
        return value
    mapping = _as_mapping(value)
    if mapping is not None:
        return str(
            mapping.get("name", mapping.get("title", mapping.get("id", "unknown")))
        )
    return str(value)


def _redact_save(value: object, key: str | None = None) -> object:
    sensitive = {
        "name",
        "title",
        "id",
        "class_name",
        "location",
        "bosses",
        "bonfires",
        "requirement",
    }
    mapping = _as_mapping(value)
    if mapping is not None:
        return {str(k): _redact_save(v, str(k).casefold()) for k, v in mapping.items()}
    if isinstance(value, list):
        values = cast(list[object], value)
        if key in {"bosses", "bonfires"}:
            return ["hidden until spoilers are permitted" for _ in values]
        return [_redact_save(item, key) for item in values]
    if key in sensitive and isinstance(value, str):
        return "hidden until spoilers are permitted"
    return value


GUIDE_WARNING = (
    "Local guide lookup: transformed from the user-provided PSNProfiles platinum-guide PDF; "
    "spoiler-heavy, non-authoritative, not save/parser truth, and not permission to republish the PDF or its text."
)


def _guide_json(value: object) -> None:
    if isinstance(value, list):
        if not value:
            _json({"results": [], "warning": GUIDE_WARNING})
        else:
            rendered: list[object] = []
            for row in cast(list[object], value):
                mapping = _as_mapping(row)
                rendered.append(
                    {**mapping, "warning": GUIDE_WARNING}
                    if mapping is not None
                    else row
                )
            _json(rendered)
    else:
        mapping = _as_mapping(value)
        if mapping is not None:
            _json({**mapping, "warning": GUIDE_WARNING})
        else:
            _json({"value": value, "warning": GUIDE_WARNING})


def cmd_fresh(_: argparse.Namespace) -> None:
    print("Dark Souls Remastered — fresh start")
    print(
        "  Priorities: unlock the first hub, meet weapon requirements, and reinforce one main weapon."
    )
    print("  Keep equip load below 25% for fast roll or below 50% for mid roll.")
    print("  Vitality 30 and Endurance 40 are useful early planning breakpoints.")
    print(
        "  Estus is improved at bonfires; do not assume an unverified save parser result."
    )
    print("  Next: softcaps | origins | build | weapons | estus")


def cmd_softcaps(_: argparse.Namespace) -> None:
    print("=== DS1 stat softcaps ===")
    for stat, points in SOFTCAPS.items():
        print(
            f"{stat.title()}: "
            + "; ".join(f"{level} ({desc})" for level, desc in points)
        )


def cmd_origins(args: argparse.Namespace) -> None:
    query = (_optional_str(args, "filter") or "").lower()
    aliases = {
        "str": "warrior",
        "strength": "warrior",
        "dex": "wanderer",
        "dexterity": "wanderer",
        "int": "sorcerer",
        "faith": "cleric",
        "fth": "cleric",
        "pyro": "pyromancer",
        "quality": "knight",
    }
    selected = [
        name
        for name in ORIGINS
        if not query or query in name or name == aliases.get(query)
    ]
    if query and not selected:
        _die(f"unknown origin/filter '{query}'; valid origins: {', '.join(ORIGINS)}")
    print("Class          SL VIT ATT END STR DEX INT FTH RES")
    for name in selected:
        row = ORIGINS[name]
        print(
            f"{name.title():<13} {row['level']:>2} {row['vit']:>3} {row['att']:>3} {row['end']:>3} {row['str']:>3} {row['dex']:>3} {row['int']:>3} {row['fth']:>3} {row['res']:>3}"
        )


def cmd_build(args: argparse.Namespace) -> None:
    kind = _optional_str(args, "type") or "quality"
    presets: dict[str, tuple[str, dict[str, int], str]] = {
        "quality": (
            "knight",
            {"vit": 27, "end": 40, "str": 40, "dex": 40},
            "balanced physical weapons",
        ),
        "strength": (
            "bandit",
            {"vit": 30, "end": 40, "str": 40, "dex": 14},
            "strength-scaling weapons; two-hand at 27 STR",
        ),
        "dexterity": (
            "wanderer",
            {"vit": 30, "end": 40, "str": 14, "dex": 40},
            "dexterity-scaling weapons",
        ),
        "sorcerer": (
            "sorcerer",
            {"vit": 27, "att": 19, "end": 30, "int": 40},
            "sorceries; attunement determines slots",
        ),
        "pyromancer": (
            "pyromancer",
            {"vit": 27, "att": 16, "end": 30, "int": 30, "fth": 30},
            "pyromancy and hybrid physical damage",
        ),
        "cleric": (
            "cleric",
            {"vit": 27, "att": 16, "end": 30, "fth": 30},
            "miracles and faith weapons",
        ),
        "sorcery": (
            "sorcerer",
            {"vit": 27, "att": 19, "end": 30, "int": 40},
            "sorceries; attunement determines slots",
        ),
        "miracle": (
            "cleric",
            {"vit": 27, "att": 19, "end": 30, "fth": 30},
            "miracles; attunement determines slots",
        ),
        "dragon": (
            "warrior",
            {"vit": 30, "end": 40, "str": 40, "dex": 40},
            "dragon weapons and physical scaling",
        ),
    }
    if kind not in presets:
        _die(f"unknown build '{kind}'; valid: {', '.join(presets)}")
    origin, stats, note = presets[kind]
    print(f"=== {kind.title()} build (target SL {_required_int(args, 'level')}) ===")
    print(f"Origin: {origin.title()} | Focus: {note}")
    print(
        "Targets: "
        + ", ".join(f"{key.upper()} {value}" for key, value in stats.items())
    )
    print(
        "Adjust VIT/END first for survivability; this is a planning baseline, not a save-backed character state."
    )


def cmd_soul_cost(args: argparse.Namespace) -> None:
    try:
        total = soul_cost(_required_int(args, "current"), _required_int(args, "target"))
    except ValueError as exc:
        _die(str(exc))
    print(
        f"Levels: {max(0, _required_int(args, 'target') - _required_int(args, 'current'))}"
    )
    print(f"Souls required: {total:,}")


def cmd_upgrade(args: argparse.Namespace) -> None:
    path = UPGRADE_PATHS.get(_required_str(args, "type"))
    if path is None:
        _die(
            f"unknown upgrade type '{_required_str(args, 'type')}'; valid: {', '.join(UPGRADE_PATHS)}"
        )
    if _required_int(args, "level") < 1:
        _die("target upgrade level must be positive")
    target = min(_required_int(args, "level"), len(path))
    cumulative: dict[str, int] = {}
    for _, end, mats in path:
        for key, count in mats.items():
            cumulative[key] = cumulative.get(key, 0) + count
        if end == target:
            print(f"=== {_required_str(args, 'type')} +{target} ===")
            if cumulative:
                print(
                    "  "
                    + ", ".join(
                        f"{count}x {key.replace('_', ' ')}"
                        for key, count in cumulative.items()
                    )
                )
            else:
                print(
                    "  No material schedule; this path is reinforced directly by its trainer."
                )
            if _required_int(args, "level") > len(path):
                print(f"  Max for this path is +{len(path)}.")
            return
    _die("upgrade path does not contain that level")


def cmd_equip_load(args: argparse.Namespace) -> None:
    try:
        maximum = equip_load_max(
            _required_int(args, "endurance"),
            _flag(args, "havels"),
            _flag(args, "favor"),
        )
    except ValueError as exc:
        _die(str(exc))
    print(f"Max equip load: {maximum:.2f}")
    print(f"Fast roll (<=25%): <= {maximum * 0.25:.2f}")
    print(f"Mid roll (<=50%): <= {maximum * 0.50:.2f}")
    print(f"Fat roll (<=100%): <= {maximum:.2f}")


def cmd_estus(args: argparse.Namespace) -> None:
    print("=== Estus and kindling (DS1) ===")
    if _required_str(args, "sub") in ("max", "shards"):
        print(
            f"Estus Shards: {ESTUS_SHARDS_MAX} total (not all shard ownership is save-validated)."
        )
    if _required_str(args, "sub") in ("max", "souls"):
        print(
            f"Fire Keeper Souls: {FIRE_KEEPER_SOULS_MAX} planned upgrades; potency is separate from flask count."
        )
    if _required_str(args, "sub") in ("max", "kindling"):
        print(
            f"Kindling levels: {', '.join(map(str, KINDLING_LEVELS))}; Rite of Kindling enables 20 uses at a bonfire."
        )
    if _required_str(args, "sub") == "max":
        print(
            f"Maximum carried flasks: {ESTUS_MAX}; exact current split is save-dependent."
        )


def cmd_farm(args: argparse.Namespace) -> None:
    farms = {
        "souls": (
            "repeatable high-density enemies in a reached area",
            "Use a safe loop and reset at a bonfire.",
        ),
        "titanite": (
            "merchant/mining routes appropriate to the upgrade tier",
            "Check the upgrade path before spending limited slabs.",
        ),
        "humanity": (
            "rats or other enemies in an already reached area",
            "Item Discovery improves drop odds; exact rates are source-sensitive.",
        ),
        "moss": (
            "early forest-area enemies",
            "Do not infer area access from a generic route.",
        ),
    }
    key = _optional_str(args, "item") or "souls"
    if key not in farms:
        _die(f"unknown farm target '{key}'; valid: {', '.join(farms)}")
    location, note = farms[key]
    print(
        f"{key.title()}: {location if _flag(args, 'spoilers') else 'a safe, already-reached farming loop'}"
    )
    print(note)


def _catalog_items(
    kind: str, query: str | None = None, *, spoilers: bool = False
) -> list[object]:
    module = _need_catalog()
    names = {
        "weapons": ("list_weapons", "weapons"),
        "rings": ("list_rings", "rings"),
        "goods": ("list_goods", "list_goods_magic", "goods_magic"),
    }[kind]
    value = _call(module, names, query or "")
    if not isinstance(value, list):
        return []
    rows = cast(list[object], value)
    if spoilers or query:
        return rows
    result: list[object] = []
    for row in rows:
        mapping = _as_mapping(row)
        if mapping is None or _numeric_int(mapping.get("spoiler_level", 0)) <= 0:
            result.append(row)
    return result


def cmd_weapons(args: argparse.Namespace) -> None:
    module = _need_catalog()
    if _optional_str(args, "name"):
        result = _call(
            module,
            ("weapon_lookup", "lookup_weapon", "find_weapon"),
            _optional_str(args, "name"),
        )
        if result is None:
            _die(f"weapon not found: {_optional_str(args, 'name')}")
        mapping = _as_mapping(result)
        if (
            mapping is not None
            and not _flag(args, "spoilers")
            and _numeric_int(mapping.get("spoiler_level", 0)) > 0
        ):
            _die("weapon details are hidden; rerun with --spoilers")
        _json(result) if _flag(args, "json") else print(result)
        return
    rows = _catalog_items("weapons", spoilers=_flag(args, "spoilers"))[
        : _required_int(args, "limit")
    ]
    if not rows:
        _die("weapon catalog is unavailable")
    if _flag(args, "json"):
        _json(rows)
    else:
        for row in rows:
            print(_name(row))


def cmd_rings(args: argparse.Namespace) -> None:
    rows = _catalog_items(
        "rings", _optional_str(args, "name"), spoilers=_flag(args, "spoilers")
    )[: _required_int(args, "limit")]
    if _flag(args, "json"):
        _json(rows)
    else:
        for row in rows:
            print(_name(row))


def cmd_goods(args: argparse.Namespace) -> None:
    rows = _catalog_items(
        "goods", _optional_str(args, "name"), spoilers=_flag(args, "spoilers")
    )[: _required_int(args, "limit")]
    if _flag(args, "json"):
        _json(rows)
    else:
        for row in rows:
            print(_name(row))


def cmd_calc(args: argparse.Namespace) -> None:
    module = _need_catalog()
    result = _call(
        module,
        ("weapon_ar", "calculate_ar", "calc_ar"),
        _required_str(args, "weapon"),
        {
            "strength": _required_int(args, "str"),
            "dexterity": _required_int(args, "dex"),
            "intelligence": _required_int(args, "int"),
            "faith": _required_int(args, "fth"),
        },
    )
    _json(result) if _flag(args, "json") else print(f"Approximate AR: {result}")


def cmd_compare(args: argparse.Namespace) -> None:
    module = _need_catalog()
    result = _call(
        module,
        ("compare_weapons", "compare"),
        [_required_str(args, "weapon_a"), _required_str(args, "weapon_b")],
        {
            "strength": _required_int(args, "str"),
            "dexterity": _required_int(args, "dex"),
            "intelligence": _required_int(args, "int"),
            "faith": _required_int(args, "fth"),
        },
    )
    _json(result) if _flag(args, "json") else print(result)


def _display_progress(rows: Sequence[Mapping[str, object]], spoilers: bool) -> None:
    for area in rows:
        name = str(area.get("name", area.get("id", "unknown")))
        visible = name if spoilers else "an unreached area"
        print(f"{area.get('order', '?')}. {visible}")
        bosses = _string_values(area.get("bosses", ()))
        if spoilers:
            print("   bosses: " + ", ".join(bosses))


def cmd_areas(args: argparse.Namespace) -> None:
    _display_progress(_area_rows(), _flag(args, "spoilers"))


def cmd_bosses(args: argparse.Namespace) -> None:
    rows = _area_rows()
    area_filter = _optional_str(args, "area")
    if area_filter:
        rows = tuple(
            row
            for row in rows
            if area_filter.lower() in str(row.get("id", "")).lower()
            or area_filter.lower() in str(row.get("name", "")).lower()
        )
        if not rows:
            _die(f"unknown area: {area_filter}")
    count = sum(len(_string_values(row.get("bosses", ()))) for row in rows)
    if not _flag(args, "spoilers"):
        print(f"Bosses tracked: {count} (names hidden; use --spoilers)")
        return
    for row in rows:
        print(f"{row['name']}: " + ", ".join(_string_values(row.get("bosses", ()))))


def cmd_route(args: argparse.Namespace) -> None:
    defeated = {
        x.strip().lower()
        for x in (_optional_str(args, "defeated") or "").split(",")
        if x.strip()
    }
    for area in _area_rows():
        bosses = _string_values(area.get("bosses", ()))
        done = bool(bosses) and all(x.lower() in defeated for x in bosses)
        label = str(area["name"]) if _flag(args, "spoilers") else "an unreached area"
        print(f"{area['order']}. {label}: {'complete' if done else 'next/optional'}")


def cmd_achievements(args: argparse.Namespace) -> None:
    rows = _resource_rows("achievement_checklist.json", "achievements")
    if not rows:
        print("Achievement checklist resource unavailable.")
        return
    if not _flag(args, "spoilers"):
        print(f"{len(rows)} checklist entries (names hidden; use --spoilers).")
        return
    for row in rows:
        if _flag(args, "missable") and not bool(row.get("missable", False)):
            continue
        print(f"- {_name(row)}")


def _source_policy() -> None:
    print(
        "Local: deterministic DS1 mechanics, bundled catalog metadata, validated save fields only."
    )
    print(
        "Live: current source status, contested mechanics, exact locations, and guide context."
    )
    print(
        "Cache: DS1_CACHE_DIR transport cache only, 24-hour TTL; cite source keys/URLs, never cache files."
    )
    print(
        "PDF: transformed local JSONL chunks only; copyrighted source text is not tracked or copied."
    )


def cmd_sources(args: argparse.Namespace) -> None:
    sources = load_sources()
    action = _optional_str(args, "sources_action") or "list"
    if action == "policy":
        _source_policy()
        return
    if action == "list":
        for key, source in sorted(sources.items()):
            print(f"{key}: {source.name} [{source.source_type}] {source.url}")
        return
    if action == "status":
        print(f"Cache directory: {cache_dir()}")
        for key in sorted(sources):
            source = sources[key]
            if source.url.startswith("local://"):
                state = "bundled/local (not fetchable)"
            else:
                state = (
                    "fresh"
                    if cache_get(key, source.url) is not None
                    else "missing/stale"
                )
            print(f"{key}: {state}")
        return
    if action == "explain":
        source = sources.get(_required_str(args, "key"))
        if source is None:
            _die(f"unknown source key: {_required_str(args, 'key')}")
        print(
            f"{source.name}\nURL: {source.url}\nLicense: {source.license}\nType: {source.source_type}"
        )
        if source.provenance:
            print(f"Provenance: {source.provenance}")
        if source.risk:
            print(f"Risk: {source.risk}")
        print("Allowed use: " + ("; ".join(source.allowed_use) or "not specified"))
        print(
            "Not allowed for: " + ("; ".join(source.not_allowed_for) or "not specified")
        )
        return
    if action == "refresh":
        keys = _str_list(args, "keys") or list(sources)
        for key in keys:
            source = sources.get(key)
            if source is None or not source.url:
                _die(f"unknown or URL-less source key: {key}")
            if source.url.startswith("local://"):
                print(f"{key}: bundled/local source; refresh skipped (not fetchable)")
                continue
            try:
                content = fetch_cached(key, source.url, force=_flag(args, "force"))
            except Exception as exc:
                print(f"{key}: refresh failed ({exc})", file=sys.stderr)
                continue
            print(f"{key}: cached {len(content)} bytes")
        return
    _die(f"unknown sources action: {action}")


def cmd_guide(args: argparse.Namespace) -> None:
    action = _optional_str(args, "guide_action") or "info"
    if action == "info":
        manifest = _guide_manifest()
        print(GUIDE_WARNING)
        print("Local transformed DSR platinum guide corpus.")
        for key in (
            "title",
            "authors",
            "url",
            "source_type",
            "provenance",
            "constraints",
        ):
            if key not in manifest:
                continue
            value = manifest[key]
            rendered = (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list))
                else value
            )
            print(f"{key}: {rendered}")
        print(f"chunks: {len(_guide_rows())}")
        return
    rows = _guide_rows()
    if action == "kinds":
        print(GUIDE_WARNING)
        print("\n".join(sorted({str(row["k"]) for row in rows})))
        return
    if action == "headings":
        print(GUIDE_WARNING)
        if not _flag(args, "spoilers"):
            heading_count = len(
                dict.fromkeys(" > ".join(str(x) for x in row["h"]) for row in rows)
            )
            print(f"{heading_count} heading paths (hidden; use --spoilers)")
        else:
            print(
                "\n".join(
                    dict.fromkeys(" > ".join(str(x) for x in row["h"]) for row in rows)
                )
            )
        return
    if action == "get":
        if _required_int(args, "row") < 1 or _required_int(args, "row") > len(rows):
            _die(f"guide row out of range: {_required_int(args, 'row')}")
        row = rows[_required_int(args, "row") - 1]
        if not _flag(args, "spoilers"):
            result: object = {"row": _required_int(args, "row"), "spoilers": "hidden"}
            if _flag(args, "json"):
                _guide_json(result)
            else:
                print(GUIDE_WARNING)
                print(
                    f"Guide row {_required_int(args, 'row')} found; content hidden (use --spoilers)."
                )
        elif _flag(args, "json"):
            _guide_json(row)
        else:
            print(GUIDE_WARNING)
            print(
                f"Row {_required_int(args, 'row')}: {' > '.join(row['h'])}\n{row['t']}"
            )
        return
    if action == "search":
        try:
            matches = _search_guide(
                " ".join(_str_list(args, "query")),
                kind=_optional_str(args, "kind"),
                heading=_optional_str(args, "heading"),
                limit=_required_int(args, "limit"),
            )
        except ValueError as exc:
            _die(str(exc))
        if not _flag(args, "spoilers"):
            result = [{"row": row["row"], "spoilers": "hidden"} for row in matches]
            if _flag(args, "json"):
                _guide_json(result)
            else:
                print(GUIDE_WARNING)
                print(
                    f"{len(matches)} guide rows matched; names/text hidden (use --spoilers)."
                )
        elif _flag(args, "json"):
            _guide_json(matches)
        else:
            print(GUIDE_WARNING)
            for row in matches:
                print(f"Row {row['row']}: {row['snippet']}")
        return
    _die(f"unknown guide action: {action}")


TRANSCRIPT_WARNING = (
    "Local automatic-caption transcript lookup: user-provided English en-orig YouTube "
    "captions; spoiler-heavy, non-authoritative, and recognition errors are possible. "
    "This corpus is not mechanics/save/parser/route truth or a route recommendation."
)

_TRANSCRIPT_HIDDEN_KEYS = frozenset(
    {
        "caption_track",
        "chunk_id",
        "chunk_ids",
        "display_name",
        "h",
        "heading",
        "headings",
        "id",
        "identifier",
        "name",
        "provenance",
        "sha256",
        "snippet",
        "source",
        "source_id",
        "source_sha256",
        "source_url",
        "t",
        "text",
        "title",
        "track",
        "tracks",
        "transcript",
        "url",
        "urls",
        "video",
        "video_id",
        "video_ids",
        "video_title",
        "video_url",
    }
)


def _redact_transcript(value: object, key: str | None = None) -> object:
    normalized = key.casefold() if key is not None else None
    if isinstance(value, str) and value.casefold().startswith(
        ("http://", "https://", "www.")
    ):
        return "hidden until spoilers are permitted"
    if normalized in _TRANSCRIPT_HIDDEN_KEYS:
        return "hidden until spoilers are permitted"
    mapping = _as_mapping(value)
    if mapping is not None:
        return {
            str(item_key): _redact_transcript(item_value, str(item_key))
            for item_key, item_value in mapping.items()
        }
    if isinstance(value, list):
        return [_redact_transcript(item, key) for item in cast(list[object], value)]
    return value


def _transcript_json(value: object) -> None:
    if isinstance(value, list):
        values = cast(list[object], value)
        if not values:
            _json({"results": [], "warning": TRANSCRIPT_WARNING})
            return
        rendered: list[object] = []
        for item in values:
            mapping = _as_mapping(item)
            rendered.append(
                {**mapping, "warning": TRANSCRIPT_WARNING}
                if mapping is not None
                else item
            )
        _json(rendered)
        return
    mapping = _as_mapping(value)
    if mapping is not None:
        _json({**mapping, "warning": TRANSCRIPT_WARNING})
    else:
        _json({"value": value, "warning": TRANSCRIPT_WARNING})


def _transcript_call_summary(*, spoilers: bool) -> Mapping[str, object]:
    try:
        value = transcript_summary(spoilers=spoilers)
    except Exception as exc:
        _die(str(exc) or "transcript summary failed")
    mapping = _as_mapping(value)
    if mapping is None:
        _die("transcript summary returned an invalid object")
    return mapping


def _transcript_rows(summary: Mapping[str, object]) -> list[object]:
    videos = summary.get("videos")
    if isinstance(videos, list):
        return cast(list[object], videos)
    count = summary.get("video_count")
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        return [{"video_index": index, "spoilers": "hidden"} for index in range(count)]
    return []


def _transcript_print_summary(
    summary: Mapping[str, object], *, action: str, spoilers: bool, as_json: bool
) -> None:
    rendered: object = summary if spoilers else _redact_transcript(summary)
    if as_json:
        _transcript_json(rendered)
        return
    print(TRANSCRIPT_WARNING)
    print(f"Transcript {action}:")
    if isinstance(rendered, Mapping):
        for key in sorted(rendered):
            value = rendered[key]
            if isinstance(value, (dict, list)):
                value_text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            else:
                value_text = str(value)
            print(f"{key}: {value_text}")
    else:
        print(str(rendered))


def cmd_transcript(args: argparse.Namespace) -> None:
    action = _optional_str(args, "transcript_action") or "info"
    spoilers = _flag(args, "spoilers")
    as_json = _flag(args, "json")
    if action in {"info", "list"}:
        summary = _transcript_call_summary(spoilers=spoilers)
        if action == "list":
            rows = _transcript_rows(summary)
            value: object = rows
            if not spoilers:
                value = _redact_transcript(value)
            if as_json:
                _transcript_json(value)
            else:
                print(TRANSCRIPT_WARNING)
                for row in cast(list[object], value):
                    print(json.dumps(row, ensure_ascii=False, sort_keys=True))
            return
        _transcript_print_summary(
            summary, action="info", spoilers=spoilers, as_json=as_json
        )
        return
    if action == "search":
        query_parts = _str_list(args, "query")
        query = " ".join(query_parts).strip()
        if not query:
            # A query-less search is deliberately summary-only, even with spoilers.
            summary = _transcript_call_summary(spoilers=spoilers)
            _transcript_print_summary(
                summary, action="search summary", spoilers=spoilers, as_json=as_json
            )
            return
        video_index = _value(args, "video_index")
        if video_index is not None and (
            not isinstance(video_index, int) or isinstance(video_index, bool)
        ):
            _die("argument 'video_index' must be an integer or null")
        limit = _required_int(args, "limit")
        try:
            matches = search_transcript(
                query,
                video_index=cast(int | None, video_index),
                limit=limit,
                spoilers=spoilers,
            )
        except Exception as exc:
            _die(str(exc) or "transcript search failed")
        rows = list(cast(Sequence[object], matches))
        if not spoilers:
            hidden_rows: list[object] = []
            for row in rows:
                mapping = _as_mapping(row)
                if mapping is None:
                    continue
                hidden_rows.append(
                    {
                        key: mapping[key]
                        for key in ("video_index", "chunk_index")
                        if key in mapping
                    }
                    | {"spoilers": "hidden"}
                )
            rows = hidden_rows
        if as_json:
            _transcript_json(rows)
        elif not spoilers:
            print(TRANSCRIPT_WARNING)
            print(
                f"{len(rows)} transcript chunks matched; "
                "names/text hidden (use --spoilers)."
            )
        else:
            print(TRANSCRIPT_WARNING)
            for row in rows:
                print(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return
    if action == "get":
        video_index = _required_int(args, "video_index")
        chunk_index = _required_int(args, "chunk_index")
        try:
            row = get_transcript_chunk(video_index, chunk_index, spoilers=spoilers)
        except Exception as exc:
            _die(str(exc) or "transcript chunk lookup failed")
        if not spoilers:
            row = {
                key: value
                for key, value in (_as_mapping(row) or {}).items()
                if key in {"video_index", "chunk_index"}
            }
            row["spoilers"] = "hidden"
        if as_json:
            _transcript_json(row)
        elif not spoilers:
            print(TRANSCRIPT_WARNING)
            print(
                f"Transcript chunk {video_index}/{chunk_index} found; "
                "names/text hidden (use --spoilers)."
            )
        else:
            print(TRANSCRIPT_WARNING)
            print(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return
    _die(f"unknown transcript action: {action}")


def cmd_audit(_: argparse.Namespace) -> None:
    errors = list(audit_core())
    required = (
        "name",
        "url",
        "license",
        "source_type",
        "allowed_use",
        "not_allowed_for",
        "risk",
        "machine_readable",
        "copyable",
    )
    registry_value = cast(object, load_json_resource("source_registry.json", {}))
    registry = _as_mapping(registry_value)
    entries = _as_mapping(registry.get("entries", {})) if registry is not None else None
    if entries is None or not entries:
        errors.append("source registry missing entries")
        entries = {}
    for key, value in entries.items():
        mapping = _as_mapping(value)
        if mapping is None:
            errors.append(f"source {key} is not an object")
            continue
        missing = [field for field in required if field not in mapping]
        if missing:
            errors.append(f"source {key} missing metadata: {', '.join(missing)}")
    for key, source in SOURCES.items():
        if not source.name or not source.url:
            errors.append(f"source {key} missing name/url")
    try:
        rows = _guide_rows()
        for row in rows:
            if set(row) < {"h", "k", "t", "row"}:
                errors.append("guide row schema incomplete")
    except Exception as exc:
        errors.append(str(exc))
    if catalog is not None:
        checker = _get_callable(catalog, "audit_catalog")
        if checker is not None:
            result = checker()
            if isinstance(result, list):
                errors.extend(str(x) for x in cast(list[object], result))
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        raise SystemExit(1)
    print("OK: DS1 core, source metadata, guide schema, and catalog checks passed")


def _read_track(path: str) -> Mapping[str, object]:
    try:
        value = cast(object, json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        _die(f"cannot read tracking JSON: {exc}")
    mapping = _as_mapping(value)
    if mapping is None:
        _die("tracking JSON must be an object")
    return mapping


def cmd_track(args: argparse.Namespace) -> None:
    data = _read_track(_required_str(args, "path"))
    section = _optional_str(args, "section")
    selected: object = data if section is None else data.get(section, {})
    print(json.dumps(selected, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_recommend(args: argparse.Namespace) -> None:
    data = _read_track(_required_str(args, "path"))
    print(
        "Recommendations are deterministic and based only on supplied tracking fields."
    )
    if not data:
        print("No tracked state; start with fresh, build, or estus.")
    elif data.get("weapon") is None:
        print("Choose one main weapon and inspect its upgrade path.")
    else:
        print(f"Keep improving tracked weapon: {data['weapon']}")


def cmd_save(args: argparse.Namespace) -> None:
    module = _need_save()
    readers: dict[str, tuple[str, ...]] = {
        "summary": ("read_summary",),
        "stats": ("read_stats",),
        "name": ("read_name",),
        "level": ("read_level",),
        "currency": ("read_currency",),
        "inventory": ("read_inventory",),
        "owned": ("owned_item_names",),
        "bosses": ("read_bosses",),
        "bonfires": ("read_bonfires",),
        "progress": ("read_progress",),
        "completion": ("read_completion_status",),
        "achievements": ("read_achievements",),
    }
    action = str(_required_str(args, "action"))
    result: object = None
    if action in {"checklist", "missed"}:
        result = {
            "supported": False,
            "reason": f"save action '{action}' is not validated for DSR",
        }
    elif action not in readers:
        _die(f"unknown save action: {action}")
    else:
        candidates: list[str]
        if _required_str(args, "save_path") == "auto":
            finder = _get_callable(module, "_default_candidates")
            if finder is not None:
                found_candidates = finder()
                if isinstance(found_candidates, Sequence) and not isinstance(
                    found_candidates, (str, bytes)
                ):
                    candidates = [
                        str(candidate)
                        for candidate in cast(Sequence[object], found_candidates)
                    ]
                else:
                    candidates = []
            else:
                found = _call(module, ("find_save_path",))
                candidates = [str(found)] if found else []
            if not candidates:
                _die("no validated DSR save found")
        else:
            candidates = [str(_required_str(args, "save_path"))]
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                reader = next(
                    (_get_callable(module, name) for name in readers[action]), None
                )
                if reader is None:
                    _die(f"required API is missing: {' / '.join(readers[action])}")
                result = reader(candidate)
                break
            except Exception as exc:
                last_error = exc
        if result is None:
            _die(f"save read failed: {last_error}")
    mapping = _as_mapping(result)
    if mapping is not None and mapping.get("supported") is False:
        rendered = _redact_save(result) if not _flag(args, "spoilers") else result
        if _flag(args, "json"):
            _json(rendered)
        else:
            print(
                f"Unsupported: {mapping.get('reason', 'save category is not validated')}"
            )
        return
    if not _flag(args, "spoilers"):
        result = _redact_save(result)
    if (
        not _flag(args, "spoilers")
        and action in {"bosses", "bonfires"}
        and isinstance(result, list)
    ):
        print(f"{action}: {len(result)} records; names hidden (use --spoilers)")
        return
    _json(result) if _flag(args, "json") else print(result)


def _frame_record_line(row: object) -> str:
    mapping = _as_mapping(row)
    if mapping is None:
        return _name(row)
    label = _name(mapping)
    timing_keys = (
        "start_seconds",
        "end_seconds",
        "start_frame_30fps",
        "end_frame_30fps",
    )
    timing = [f"{key}={mapping[key]}" for key in timing_keys if key in mapping]
    return f"{label}: " + ", ".join(timing) if timing else label


def cmd_frames(args: argparse.Namespace) -> None:
    module = _need_frames()
    install = _required_str(args, "install")
    kind = _required_str(args, "kind")
    query = _optional_str(args, "query")
    limit = _required_int(args, "limit")
    spoilers = _flag(args, "spoilers")
    scan = _call(module, ("scan_install",), install)
    view = _call(
        module,
        ("select_frame_records",),
        scan,
        kind=kind,
        query=query,
        spoilers=spoilers,
        limit=limit,
    )
    rendered = _call(module, ("to_jsonable",), view)
    payload = _as_mapping(rendered)
    if payload is None:
        _die("frame scanner returned an invalid view")
    if _flag(args, "json"):
        _json(payload)
        return
    records_value = payload.get("records", ())
    records = (
        cast(Sequence[object], records_value)
        if isinstance(records_value, Sequence)
        and not isinstance(records_value, (str, bytes))
        else ()
    )
    if not spoilers and query is None:
        counts = _as_mapping(payload.get("counts"))
        if counts is None:
            summary = _as_mapping(payload.get("summary"))
            counts = (
                {
                    key: value
                    for key, value in summary.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
                if summary is not None
                else None
            )
        if counts:
            count_text = ", ".join(
                f"{key}={value}" for key, value in sorted(counts.items())
            )
            print(f"Frame scan summary: {count_text}")
        else:
            print(f"Frame scan summary: {len(records)} records")
        print("Names and timing hidden; use a query or --spoilers.")
        return
    if not records:
        print("No frame records matched.")
        return
    for row in records:
        print(_frame_record_line(row))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="darksouls", description="Spoiler-safe Dark Souls Remastered companion"
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("fresh")
    sub.add_parser("softcaps")
    p = sub.add_parser("origins")
    p.add_argument("filter", nargs="?")
    p = sub.add_parser("build")
    p.add_argument(
        "type",
        nargs="?",
        choices=(
            "quality",
            "strength",
            "dexterity",
            "sorcerer",
            "sorcery",
            "pyromancer",
            "cleric",
            "miracle",
            "dragon",
        ),
    )
    p.add_argument("--level", type=int, default=100)
    p = sub.add_parser("soul-cost")
    p.add_argument("current", type=int)
    p.add_argument("target", type=int)
    p = sub.add_parser("upgrade")
    p.add_argument("level", type=int)
    p.add_argument("--type", choices=tuple(UPGRADE_PATHS), default="normal")
    p = sub.add_parser("equip-load")
    p.add_argument("--endurance", type=int, default=40)
    rings = p.add_mutually_exclusive_group()
    rings.add_argument("--havels", action="store_true")
    rings.add_argument("--favor", action="store_true")
    p = sub.add_parser("estus")
    p.add_argument(
        "sub", choices=("max", "shards", "souls", "kindling"), nargs="?", default="max"
    )
    p = sub.add_parser("farm")
    p.add_argument("item", choices=("souls", "titanite", "humanity", "moss"), nargs="?")
    p.add_argument("--spoilers", action="store_true")
    p = sub.add_parser("frames", help="read-only local DSR frame scan")
    p.add_argument("--install", required=True)
    p.add_argument("query", nargs="?")
    p.add_argument("--kind", choices=("all", "weapon", "item"), default="all")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.add_argument("--spoilers", action="store_true")
    for command, help_text in (
        ("weapons", "weapon catalog"),
        ("rings", "ring catalog"),
        ("goods", "goods/magic catalog"),
    ):
        p = sub.add_parser(command, help=help_text)
        p.add_argument("name", nargs="?")
        p.add_argument("--limit", type=int, default=50)
        p.add_argument("--json", action="store_true")
        p.add_argument("--spoilers", action="store_true")
        p.add_argument("--all", action="store_true")
    p = sub.add_parser("calc")
    p.add_argument("weapon")
    p.add_argument("str", type=int)
    p.add_argument("dex", type=int)
    p.add_argument("--int", type=int, default=10)
    p.add_argument("--fth", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("compare")
    p.add_argument("weapon_a")
    p.add_argument("weapon_b")
    p.add_argument("--str", type=int, default=40)
    p.add_argument("--dex", type=int, default=40)
    p.add_argument("--int", type=int, default=10)
    p.add_argument("--fth", type=int, default=10)
    p.add_argument("--json", action="store_true")
    for command in ("areas", "bosses", "route"):
        p = sub.add_parser(command)
        p.add_argument("--spoilers", action="store_true")
    sub.choices["bosses"].add_argument("--area")
    sub.choices["route"].add_argument("--defeated")
    p = sub.add_parser("achievements")
    p.add_argument("--missable", action="store_true")
    p.add_argument("--spoilers", action="store_true")
    src = sub.add_parser("sources")
    ss = src.add_subparsers(dest="sources_action")
    ss.add_parser("list")
    ss.add_parser("status")
    ss.add_parser("policy")
    ex = ss.add_parser("explain")
    ex.add_argument("key")
    rf = ss.add_parser("refresh")
    rf.add_argument("keys", nargs="*")
    rf.add_argument("--force", action="store_true")
    guide = sub.add_parser("guide")
    gs = guide.add_subparsers(dest="guide_action")
    info = gs.add_parser("info")
    info.add_argument("--spoilers", action="store_true")
    kinds = gs.add_parser("kinds")
    kinds.add_argument("--spoilers", action="store_true")
    headings = gs.add_parser("headings")
    headings.add_argument("--spoilers", action="store_true")
    get = gs.add_parser("get")
    get.add_argument("row", type=int)
    get.add_argument("--json", action="store_true")
    get.add_argument("--spoilers", action="store_true")
    search = gs.add_parser("search")
    search.add_argument("query", nargs="+")
    search.add_argument("--kind")
    search.add_argument("--heading")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--json", action="store_true")
    search.add_argument("--spoilers", action="store_true")
    transcript = sub.add_parser(
        "transcript", help="local DSR automatic-caption transcript"
    )
    transcript.set_defaults(
        transcript_action=None,
        json=False,
        spoilers=False,
        video_index=None,
        limit=8,
    )
    transcript.add_argument("--video-index", type=int, dest="video_index")
    transcript.add_argument("--limit", type=int, default=8)
    transcript.add_argument("--json", action="store_true")
    transcript.add_argument("--spoilers", action="store_true")
    ts = transcript.add_subparsers(dest="transcript_action")

    def _transcript_action_parser(name: str) -> argparse.ArgumentParser:
        action_parser = ts.add_parser(name)
        action_parser.add_argument(
            "--json", action="store_true", default=argparse.SUPPRESS
        )
        action_parser.add_argument(
            "--spoilers", action="store_true", default=argparse.SUPPRESS
        )
        return action_parser

    _transcript_action_parser("info")
    _transcript_action_parser("list")
    search_transcript_parser = _transcript_action_parser("search")
    search_transcript_parser.add_argument("query", nargs="*")
    search_transcript_parser.add_argument(
        "--video-index", type=int, dest="video_index", default=argparse.SUPPRESS
    )
    search_transcript_parser.add_argument(
        "--limit", type=int, default=argparse.SUPPRESS
    )
    get_transcript_parser = _transcript_action_parser("get")
    get_transcript_parser.add_argument("video_index", type=int)
    get_transcript_parser.add_argument("chunk_index", type=int)

    sub.add_parser("audit")
    p = sub.add_parser("track")
    p.add_argument("--path", required=True)
    p.add_argument("section", nargs="?")
    p = sub.add_parser("recommend")
    p.add_argument("--path", required=True)
    p = sub.add_parser("save")
    p.add_argument("save_path", nargs="?", default="auto")
    p.add_argument(
        "action",
        choices=(
            "summary",
            "stats",
            "name",
            "level",
            "currency",
            "inventory",
            "owned",
            "bosses",
            "bonfires",
            "progress",
            "completion",
            "achievements",
            "checklist",
            "missed",
        ),
        nargs="?",
        default="summary",
    )
    p.add_argument("--spoilers", action="store_true")
    p.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    command = _optional_str(args, "command")
    if not command:
        cmd_fresh(args)
        return
    handlers: dict[str, Callable[[argparse.Namespace], None]] = {
        "fresh": cmd_fresh,
        "softcaps": cmd_softcaps,
        "origins": cmd_origins,
        "build": cmd_build,
        "soul-cost": cmd_soul_cost,
        "upgrade": cmd_upgrade,
        "equip-load": cmd_equip_load,
        "estus": cmd_estus,
        "farm": cmd_farm,
        "frames": cmd_frames,
        "weapons": cmd_weapons,
        "rings": cmd_rings,
        "goods": cmd_goods,
        "calc": cmd_calc,
        "compare": cmd_compare,
        "areas": cmd_areas,
        "bosses": cmd_bosses,
        "route": cmd_route,
        "achievements": cmd_achievements,
        "sources": cmd_sources,
        "guide": cmd_guide,
        "transcript": cmd_transcript,
        "audit": cmd_audit,
        "track": cmd_track,
        "recommend": cmd_recommend,
        "save": cmd_save,
    }
    handler = handlers.get(command)
    if handler is None:
        _die(f"unknown command: {command}")
    handler(args)


if __name__ == "__main__":
    main()
