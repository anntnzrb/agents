"""Dark Souls Remastered mechanics, source policy, cache and guide interfaces.

The module deliberately contains only deterministic DS1 mechanics and provenance
plumbing.  Dynamic facts are represented as source-backed resources and are never
silently presented as save truth.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TypeAlias, TypedDict, cast

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


class Area(TypedDict):
    id: str
    name: str
    order: int
    bosses: tuple[str, ...]


class GuideChunk(TypedDict):
    row: int
    h: list[str]
    k: str
    t: str


class GuideResult(GuideChunk):
    snippet: str


def _as_object(value: JsonValue) -> JsonObject | None:
    return value if isinstance(value, dict) else None


def _load_json_text(path: Path) -> JsonValue:
    return cast(JsonValue, json.loads(path.read_text(encoding="utf-8")))


CACHE_TTL_HOURS = 24
CACHE_ENV = "DS1_CACHE_DIR"
CACHE_DIR = Path(os.environ.get(CACHE_ENV, "~/.cache/darksouls-companion")).expanduser()
GAME = "Dark Souls Remastered"
UPDATED = "2026-07-11"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    name: str
    url: str
    license: str = "Unknown"
    source_type: str = "reference"
    allowed_use: tuple[str, ...] = ()
    not_allowed_for: tuple[str, ...] = ()
    risk: str = ""
    machine_readable: bool = False
    copyable: bool = False
    provenance: str = ""


def _resources_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "resources"


def resource_path(name: str) -> Path:
    return _resources_dir() / name


def load_json_resource(name: str, default: JsonValue = None) -> JsonValue:
    path = resource_path(name)
    if not path.exists():
        return default
    try:
        return _load_json_text(path)
    except (OSError, ValueError):
        return default


def _tuple_text(value: JsonValue) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(x) for x in value)
    return ()


def load_sources() -> dict[str, SourceRecord]:
    raw = load_json_resource("source_registry.json", {})
    if isinstance(raw, dict) and isinstance(raw.get("entries"), dict):
        raw = raw["entries"]
    elif isinstance(raw, dict):
        sources = raw.get("sources")
        if isinstance(sources, list):
            raw = {
                str(row.get("key", row.get("id", ""))): row
                for row in sources
                if isinstance(row, dict)
            }
    if not isinstance(raw, dict):
        return {}
    out: dict[str, SourceRecord] = {}
    for key, value in raw.items():
        entry = _as_object(value)
        if entry is None:
            continue
        out[str(key)] = SourceRecord(
            name=str(entry.get("name", key)),
            url=str(entry.get("url", "")),
            license=str(entry.get("license", "Unknown")),
            source_type=str(entry.get("source_type", "reference")),
            allowed_use=_tuple_text(entry.get("allowed_use", None)),
            not_allowed_for=_tuple_text(entry.get("not_allowed_for", None)),
            risk=str(entry.get("risk", "")),
            machine_readable=bool(entry.get("machine_readable", False)),
            copyable=bool(entry.get("copyable", False)),
            provenance=str(entry.get("provenance", entry.get("notes", ""))),
        )
    return out


SOURCES = load_sources()


def cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def _cache_file(key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip(".")
    if not safe:
        raise ValueError("cache key must contain a usable character")
    return cache_dir() / f"{safe}.json"


def cache_get(key: str, url: str | None = None) -> str | None:
    try:
        data = _as_object(_load_json_text(_cache_file(key)))
    except (OSError, ValueError):
        return None
    if data is None:
        return None
    timestamp_value = data.get("ts", 0)
    if isinstance(timestamp_value, (int, float)):
        timestamp = float(timestamp_value)
    elif isinstance(timestamp_value, str):
        try:
            timestamp = float(timestamp_value)
        except ValueError:
            return None
    else:
        return None
    if time.time() - timestamp >= CACHE_TTL_HOURS * 3600:
        return None
    if url is not None:
        meta = _as_object(data.get("meta", {}))
        if meta is None or meta.get("url") != url:
            return None
    value = data.get("content")
    return value if isinstance(value, str) else None


def cache_put(key: str, content: str, meta: dict[str, JsonValue] | None = None) -> None:
    payload: JsonObject = {
        "ts": time.time(),
        "content": content,
        "meta": {} if meta is None else meta,
    }
    _cache_file(key).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def fetch_cached(key: str, url: str, *, force: bool = False) -> str:
    if not force:
        hit = cache_get(key, url)
        if hit is not None:
            return hit
    request = urllib.request.Request(
        url, headers={"User-Agent": "darksouls-companion/1.0"}
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        content = response.read().decode("utf-8", errors="replace")
    cache_put(
        key,
        content,
        {"url": url, "sha256": hashlib.sha256(content.encode()).hexdigest()},
    )
    return content


# DS1 (not DS3) origin values.  Resistance is retained for completeness but does
# not normally enter build recommendations.
STAT_KEYS = ("vit", "att", "end", "str", "dex", "int", "fth", "res")
ORIGINS: dict[str, dict[str, int]] = {
    "warrior": {
        "level": 4,
        "vit": 11,
        "att": 9,
        "end": 12,
        "str": 13,
        "dex": 13,
        "int": 9,
        "fth": 9,
        "res": 11,
    },
    "knight": {
        "level": 5,
        "vit": 14,
        "att": 10,
        "end": 10,
        "str": 11,
        "dex": 11,
        "int": 9,
        "fth": 9,
        "res": 10,
    },
    "wanderer": {
        "level": 3,
        "vit": 10,
        "att": 11,
        "end": 10,
        "str": 10,
        "dex": 14,
        "int": 11,
        "fth": 8,
        "res": 12,
    },
    "thief": {
        "level": 5,
        "vit": 9,
        "att": 11,
        "end": 9,
        "str": 9,
        "dex": 15,
        "int": 12,
        "fth": 11,
        "res": 10,
    },
    "bandit": {
        "level": 4,
        "vit": 12,
        "att": 8,
        "end": 14,
        "str": 14,
        "dex": 9,
        "int": 8,
        "fth": 10,
        "res": 11,
    },
    "hunter": {
        "level": 4,
        "vit": 11,
        "att": 9,
        "end": 11,
        "str": 12,
        "dex": 14,
        "int": 9,
        "fth": 9,
        "res": 11,
    },
    "sorcerer": {
        "level": 3,
        "vit": 8,
        "att": 15,
        "end": 8,
        "str": 9,
        "dex": 11,
        "int": 15,
        "fth": 8,
        "res": 8,
    },
    "pyromancer": {
        "level": 1,
        "vit": 10,
        "att": 12,
        "end": 11,
        "str": 12,
        "dex": 9,
        "int": 10,
        "fth": 8,
        "res": 12,
    },
    "cleric": {
        "level": 2,
        "vit": 11,
        "att": 11,
        "end": 9,
        "str": 12,
        "dex": 8,
        "int": 8,
        "fth": 14,
        "res": 11,
    },
    "deprived": {
        "level": 6,
        "vit": 11,
        "att": 11,
        "end": 11,
        "str": 11,
        "dex": 11,
        "int": 11,
        "fth": 11,
        "res": 11,
    },
}

SOFTCAPS: dict[str, tuple[tuple[int, str], ...]] = {
    "vitality": ((27, "first practical HP softcap"), (40, "second HP softcap")),
    "endurance": ((40, "stamina softcap; further points increase equip load only"),),
    "strength": ((40, "physical scaling softcap"),),
    "dexterity": ((40, "physical scaling softcap"),),
    "intelligence": ((40, "common damage softcap"),),
    "faith": ((30, "common miracle requirement"), (50, "high-end miracle softcap")),
    "attunement": (
        (10, "one slot"),
        (12, "two slots"),
        (14, "three slots"),
        (16, "four slots"),
        (19, "five slots"),
        (23, "six slots"),
        (28, "seven slots"),
        (34, "nine slots"),
        (41, "ten slots"),
        (50, "twelve slots"),
    ),
}

ATTUNEMENT_SLOTS = (
    (0, 0),
    (10, 1),
    (12, 2),
    (14, 3),
    (16, 4),
    (19, 5),
    (23, 6),
    (28, 7),
    (34, 9),
    (41, 10),
    (50, 12),
)


def attunement_slots(level: int) -> int:
    if level < 0 or level > 99:
        raise ValueError("attunement must be between 0 and 99")
    return max(slots for threshold, slots in ATTUNEMENT_SLOTS if level >= threshold)


def vitality_hp(level: int) -> int:
    if not 1 <= level <= 99:
        raise ValueError("vitality must be between 1 and 99")
    # Piecewise interpolation over stable DS1 breakpoints; exact table values at
    # the breakpoints are deterministic and the approximation is called out.
    points = ((1, 400), (12, 572), (30, 1100), (50, 1500), (99, 1900))
    for (lo, hp_lo), (hi, hp_hi) in zip(points, points[1:]):
        if lo <= level <= hi:
            return round(hp_lo + (hp_hi - hp_lo) * (level - lo) / (hi - lo))
    return points[-1][1]


def endurance_stamina(level: int) -> int:
    if not 1 <= level <= 99:
        raise ValueError("endurance must be between 1 and 99")
    return 80 + min(level, 40)


def soul_cost(current: int, target: int) -> int:
    if not 1 <= current <= 713 or not 1 <= target <= 713:
        raise ValueError("soul levels must be between 1 and 713")
    if target <= current:
        return 0
    return sum(
        max(0, math.floor(0.02 * level**3 + 3.06 * level**2 + 105.6 * level - 895))
        for level in range(current, target)
    )


def equip_load_max(endurance: int, havels: bool = False, favor: bool = False) -> float:
    if not 0 <= endurance <= 99:
        raise ValueError("endurance must be between 0 and 99")
    if havels and favor:
        raise ValueError(
            "Havel's Ring and Ring of Favor and Protection are mutually exclusive"
        )
    value = endurance * 2.0
    if havels:
        value *= 1.5
    elif favor:
        value *= 1.2
    return round(value, 2)


def roll_type(ratio: float) -> str:
    if ratio < 0:
        raise ValueError("equip-load ratio cannot be negative")
    if ratio <= 25:
        return "fast roll"
    if ratio <= 50:
        return "mid roll"
    if ratio <= 100:
        return "fat roll"
    return "overloaded (cannot roll)"


def _material_path(
    materials: Iterable[tuple[str, int]],
) -> list[tuple[int, int, dict[str, int]]]:
    return [
        (level - 1, level, {material: count})
        for level, (material, count) in enumerate(materials, 1)
    ]


UPGRADE_PATHS: dict[str, list[tuple[int, int, dict[str, int]]]] = {
    "normal": _material_path(
        (
            ("titanite_shard", 1),
            ("titanite_shard", 1),
            ("titanite_shard", 2),
            ("titanite_shard", 2),
            ("titanite_shard", 3),
            ("large_titanite_shard", 1),
            ("large_titanite_shard", 1),
            ("large_titanite_shard", 2),
            ("large_titanite_shard", 2),
            ("large_titanite_shard", 3),
            ("titanite_chunk", 1),
            ("titanite_chunk", 1),
            ("titanite_chunk", 2),
            ("titanite_chunk", 2),
            ("titanite_slab", 1),
        )
    ),
    "raw": _material_path(
        (
            ("large_titanite_shard", 1),
            ("large_titanite_shard", 1),
            ("large_titanite_shard", 2),
            ("large_titanite_shard", 2),
            ("large_titanite_shard", 3),
        )
    ),
    "fire": _material_path(
        (
            ("green_titanite_shard", 1),
            ("green_titanite_shard", 1),
            ("green_titanite_shard", 2),
            ("green_titanite_shard", 2),
            ("green_titanite_shard", 3),
            ("red_titanite_chunk", 1),
            ("red_titanite_chunk", 1),
            ("red_titanite_chunk", 2),
            ("red_titanite_chunk", 2),
            ("red_titanite_slab", 1),
        )
    ),
    "chaos": _material_path(
        (
            ("red_titanite_chunk", 1),
            ("red_titanite_chunk", 1),
            ("red_titanite_chunk", 2),
            ("red_titanite_chunk", 2),
            ("red_titanite_slab", 1),
        )
    ),
    "lightning": _material_path(
        (
            ("titanite_chunk", 1),
            ("titanite_chunk", 1),
            ("titanite_chunk", 2),
            ("titanite_chunk", 2),
            ("titanite_slab", 1),
        )
    ),
    "magic": _material_path(
        (
            ("green_titanite_shard", 1),
            ("green_titanite_shard", 1),
            ("green_titanite_shard", 2),
            ("green_titanite_shard", 2),
            ("green_titanite_shard", 3),
            ("blue_titanite_chunk", 1),
            ("blue_titanite_chunk", 1),
            ("blue_titanite_chunk", 2),
            ("blue_titanite_chunk", 2),
            ("blue_titanite_slab", 1),
        )
    ),
    "enchanted": _material_path(
        (
            ("blue_titanite_chunk", 1),
            ("blue_titanite_chunk", 1),
            ("blue_titanite_chunk", 2),
            ("blue_titanite_chunk", 2),
            ("blue_titanite_slab", 1),
        )
    ),
    "divine": _material_path(
        (
            ("green_titanite_shard", 1),
            ("green_titanite_shard", 1),
            ("green_titanite_shard", 2),
            ("green_titanite_shard", 2),
            ("green_titanite_shard", 3),
            ("white_titanite_chunk", 1),
            ("white_titanite_chunk", 1),
            ("white_titanite_chunk", 2),
            ("white_titanite_chunk", 2),
            ("white_titanite_slab", 1),
        )
    ),
    "occult": _material_path(
        (
            ("white_titanite_chunk", 1),
            ("white_titanite_chunk", 1),
            ("white_titanite_chunk", 2),
            ("white_titanite_chunk", 2),
            ("white_titanite_slab", 1),
        )
    ),
    "unique": _material_path(tuple(("twinkling_titanite", 1) for _ in range(5))),
    "crystal": _material_path(tuple(("twinkling_titanite", 1) for _ in range(5))),
    "dragon": _material_path(tuple(("dragon_scale", 1) for _ in range(5))),
    # Flame reinforcement is direct/trainer-based; no material schedule is
    # asserted by the bundled game-data contract.
    "pyromancy": [(level - 1, level, {}) for level in range(1, 16)],
}

ESTUS_SHARDS_MAX = 7
FIRE_KEEPER_SOULS_MAX = 7
ESTUS_MAX = 20
KINDLING_LEVELS = (5, 10, 15, 20)

AREAS: tuple[Area, ...] = (
    {
        "id": "asylum",
        "name": "Northern Undead Asylum",
        "order": 1,
        "bosses": ("asylum-demon", "stray-demon"),
    },
    {
        "id": "burg",
        "name": "Undead Burg",
        "order": 2,
        "bosses": ("taurus-demon", "capra-demon"),
    },
    {
        "id": "parish",
        "name": "Undead Parish",
        "order": 3,
        "bosses": ("bell-gargoyles", "moonlight-butterfly"),
    },
    {
        "id": "darkroot",
        "name": "Darkroot Garden/Basin",
        "order": 4,
        "bosses": ("great-grey-wolf-sif",),
    },
    {"id": "depths", "name": "The Depths", "order": 5, "bosses": ("gaping-dragon",)},
    {
        "id": "blighttown",
        "name": "Blighttown",
        "order": 6,
        "bosses": ("chaos-witch-quelaag", "ceaseless-discharge"),
    },
    {"id": "catacombs", "name": "The Catacombs", "order": 7, "bosses": ("pinwheel",)},
    {"id": "sens", "name": "Sen's Fortress", "order": 8, "bosses": ("iron-golem",)},
    {
        "id": "anor-londo",
        "name": "Anor Londo",
        "order": 9,
        "bosses": ("ornstein-smough", "dark-sun-gwyndolin"),
    },
    {
        "id": "painted-world",
        "name": "Painted World of Ariamis",
        "order": 10,
        "bosses": ("crossbreed-priscilla",),
    },
    {
        "id": "dukes-archives",
        "name": "The Duke's Archives/Crystal Cave",
        "order": 11,
        "bosses": ("seath-the-scaleless",),
    },
    {
        "id": "demon-ruins",
        "name": "Demon Ruins/Lost Izalith",
        "order": 12,
        "bosses": ("demon-firesage", "centipede-demon", "bed-of-chaos"),
    },
    {
        "id": "new-londo",
        "name": "New Londo Ruins",
        "order": 13,
        "bosses": ("four-kings",),
    },
    {
        "id": "tomb",
        "name": "Tomb of the Giants",
        "order": 14,
        "bosses": ("gravelord-nito",),
    },
    {"id": "kiln", "name": "Kiln of the First Flame", "order": 15, "bosses": ("gwyn",)},
    {
        "id": "dlc",
        "name": "Oolacile (DLC)",
        "order": 16,
        "bosses": ("sanctuary-guardian", "artorias", "manus", "black-dragon-kalameet"),
    },
)


def spoiler_safe(
    name: str, *, spoilers: bool = False, known: Iterable[str] = ()
) -> str:
    if spoilers or name.lower() in {str(x).lower() for x in known}:
        return name
    return "an unreached area/boss"


# Guide corpus — transformed local chunks only (never the original PDF).
GUIDE_DIR = _resources_dir() / "guides" / "dsr_plat_guide"
GUIDE_MANIFEST_PATH = GUIDE_DIR / "dsr-plat-guide.manifest.json"
GUIDE_CHUNKS_PATH = GUIDE_DIR / "dsr-plat-guide.chunks.jsonl"
GUIDE_STOPWORDS = frozenset(
    "a an and are as at be by for from in is it of on or the this to with".split()
)


def load_guide_manifest() -> JsonObject:
    data = load_json_resource("guides/dsr_plat_guide/dsr-plat-guide.manifest.json", {})
    manifest = _as_object(data)
    if manifest is None:
        raise ValueError("invalid guide manifest")
    return manifest


def load_guide_chunks() -> list[GuideChunk]:
    if not GUIDE_CHUNKS_PATH.exists():
        raise FileNotFoundError(f"missing local guide corpus: {GUIDE_CHUNKS_PATH}")
    rows: list[GuideChunk] = []
    with GUIDE_CHUNKS_PATH.open(encoding="utf-8") as handle:
        for row, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = _as_object(cast(JsonValue, json.loads(line)))
            headings = None if value is None else value.get("h")
            kind = None if value is None else value.get("k")
            text = None if value is None else value.get("t")
            if (
                not isinstance(headings, list)
                or not isinstance(kind, str)
                or not isinstance(text, str)
            ):
                raise ValueError(f"invalid guide row {row}; expected h/k/t")
            rows.append(
                {
                    "row": row,
                    "h": [str(item) for item in headings],
                    "k": kind,
                    "t": text,
                }
            )
    return rows


def search_guide(
    query: str,
    *,
    kind: str | None = None,
    heading: str | None = None,
    limit: int = 8,
) -> list[GuideResult]:
    if not query.strip():
        raise ValueError("guide query cannot be empty")
    if limit < 1 or limit > 100:
        raise ValueError("guide limit must be between 1 and 100")
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z0-9']+", query)
        if token.lower() not in GUIDE_STOPWORDS
    ]
    if not tokens:
        raise ValueError("guide query must include a non-stopword term")
    rows = load_guide_chunks()
    # Prefer SQLite FTS5 for deterministic ranked token matching; the plain
    # substring path below remains available on builds without FTS5.
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE guide USING fts5(heading, kind, text)")
        connection.executemany(
            "INSERT INTO guide(rowid, heading, kind, text) VALUES (?, ?, ?, ?)",
            ((row["row"], " > ".join(row["h"]), row["k"], row["t"]) for row in rows),
        )
        match = " ".join(
            f'"{token.replace(chr(34), chr(34) + chr(34))}"' for token in tokens
        )
        statement = "SELECT rowid FROM guide WHERE guide MATCH ?"
        params: list[object] = [match]
        if kind:
            statement += " AND lower(kind) = lower(?)"
            params.append(kind)
        if heading:
            statement += " AND lower(heading) LIKE lower(?)"
            params.append(f"%{heading}%")
        fetched = cast(
            list[tuple[object, ...]],
            connection.execute(statement, params).fetchall(),
        )
        row_ids: set[int] = set()
        for item in fetched:
            if item and isinstance(item[0], int):
                row_ids.add(item[0])
        connection.close()
        candidates = [row for row in rows if row["row"] in row_ids]
    except sqlite3.Error:
        candidates = []
    if not candidates:
        candidates = rows
    out: list[GuideResult] = []
    for row in candidates:
        path = " > ".join(row["h"])
        haystack = f"{path} {row['k']} {row['t']}".lower()
        if tokens and not all(token in haystack for token in tokens):
            continue
        if kind and row["k"].lower() != kind.lower():
            continue
        if heading and heading.lower() not in path.lower():
            continue
        text = " ".join(row["t"].split())
        result: GuideResult = {
            "row": row["row"],
            "h": row["h"],
            "k": row["k"],
            "t": row["t"],
            "snippet": text[:280] + ("..." if len(text) > 280 else ""),
        }
        out.append(result)
        if len(out) >= limit:
            break
    return out


def audit_core() -> list[str]:
    errors: list[str] = []
    if CACHE_TTL_HOURS != 24:
        errors.append("cache TTL must be 24 hours")
    if ESTUS_SHARDS_MAX != 7 or ESTUS_MAX != 20:
        errors.append("DS1 Estus constants inconsistent")
    if not ORIGINS or "deprived" not in ORIGINS:
        errors.append("origin catalog missing")
    for key, path in (("normal", 15), ("unique", 5), ("dragon", 5)):
        if len(UPGRADE_PATHS[key]) != path:
            errors.append(f"upgrade path {key} incomplete")
    return errors
